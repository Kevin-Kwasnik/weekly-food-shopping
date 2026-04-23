import pandas as pd
from datetime import datetime, timezone

from dotenv import load_dotenv
import os
load_dotenv()

SESSION_START = datetime.now(timezone.utc)

#tracing
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.instrumentation.strands_agents import StrandsAgentsToOpenInferenceProcessor

# evals
from phoenix.client import Client
from phoenix.evals.llm import LLM
from phoenix.evals.metrics import FaithfulnessEvaluator, ToolInvocationEvaluator
from phoenix.evals import bind_evaluator, evaluate_dataframe
from phoenix.trace import suppress_tracing

# ------ tracing setup -----
resource = Resource.create({
    "service.name": "grocery-assistant",
    "model_id": "weekly-shop",
    "openinference.project.name": "weekly-shop",
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(StrandsAgentsToOpenInferenceProcessor())
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces")))
trace.set_tracer_provider(provider)

#agent sdk
from strands import Agent
from strands.models.ollama import OllamaModel
import strands.telemetry.tracer as _strands_tracer
_strands_tracer._tracer_instance = None

import tools.kroger_products

#eval
llm = LLM(
    provider="openai",
    model="qwen3-coder-next:cloud",
    client="openai",
    base_url="https://ollama.com/v1",
    api_key=os.getenv("OLLAMA_API_KEY")
)
faithfulness_eval = FaithfulnessEvaluator(llm=llm)
tool_invocation_eval = ToolInvocationEvaluator(llm=llm)

KROGER_TOOL_SCHEMA = """
search_kroger_products: Search the Kroger product catalog.
- search_term (required): Product or ingredient to search for (e.g. "chicken breast", "rice")
- location_id (optional): 8-digit Kroger store ID to scope results to a specific location
Returns top matches with product name, UPC, and regular price.
"""

model = OllamaModel(
    model_id="gpt-oss:120b-cloud",
    host="https://ollama.com"
)

system_prompt = "You are a grocery shopping agent. Please prioritize the users preferences."

agent = Agent(
    model=model,
    tools=[tools.kroger_products.search_kroger_products],
    system_prompt=system_prompt,
    callback_handler=None
)


def _log_results(client, results_df, score_col, annotation_name):
    results_df['score'] = results_df[score_col].apply(lambda x: x.get('score') if isinstance(x, dict) else None)
    results_df['label'] = results_df[score_col].apply(lambda x: x.get('label') if isinstance(x, dict) else None)
    results_df['explanation'] = results_df[score_col].apply(lambda x: x.get('explanation') if isinstance(x, dict) else None)

    print(results_df[['score', 'label', 'explanation']].to_string())

    # results_df index is context.span_id (strings) — use it directly as the annotation index
    annotations = results_df[['score', 'label', 'explanation']].copy()
    annotations.index.name = 'span_id'

    if not annotations.empty:
        client.spans.log_span_annotations_dataframe(
            dataframe=annotations,
            annotation_name=annotation_name,
            annotator_kind="LLM"
        )
        print(f"  -> {annotation_name} annotations logged — check http://localhost:6006")
    else:
        print(f"  -> No {annotation_name} annotations to log.")


def run_evals():
    """Pull spans from Phoenix, run faithfulness and tool invocation evals."""
    client = Client(base_url="http://localhost:6006")
    spans_df = client.spans.get_spans_dataframe(project_identifier="weekly-shop")

    if spans_df.empty:
        print("No spans found.")
        return

    # Filter to only spans produced in this session
    if 'start_time' in spans_df.columns:
        spans_df = spans_df[spans_df['start_time'] >= SESSION_START]

    if spans_df.empty:
        print("No spans from this session.")
        return

    agent_spans = spans_df[spans_df['span_kind'] == 'AGENT'].copy()
    tool_spans = spans_df[spans_df['span_kind'] == 'TOOL'].copy()

    if agent_spans.empty:
        print("No agent spans found to evaluate.")
        return

    # Build tool context: concatenate all tool outputs per trace, joined onto agent spans
    if not tool_spans.empty:
        tool_context = (
            tool_spans
            .groupby('context.trace_id')['attributes.output.value']
            .apply(lambda outputs: "\n\n".join(str(o) for o in outputs if o))
            .reset_index()
            .rename(columns={'attributes.output.value': 'tool_context'})
        )
        agent_spans = agent_spans.merge(tool_context, on='context.trace_id', how='left')

    # Drop spans with no Kroger tool output — faithfulness without real context is meaningless
    if 'tool_context' not in agent_spans.columns:
        print("No tool calls found — skipping faithfulness eval.")
        return
    agent_spans = agent_spans.dropna(subset=['tool_context'])
    if agent_spans.empty:
        print("No agent spans with Kroger tool output — skipping faithfulness eval.")
        return

    # Show what the judge will compare against so results can be audited
    for _, row in agent_spans.iterrows():
        print(f"\n[Faithfulness context for span {row['context.span_id'][:8]}...]")
        print(f"  Input:   {str(row['attributes.input.value'])[:120]}")
        print(f"  Context: {str(row['tool_context'])[:300]}")
        print(f"  Output:  {str(row['attributes.output.value'])[:120]}")

    # --- Faithfulness: did the agent ground its response in actual Kroger results? ---
    print(f"\nRunning faithfulness evals on {len(agent_spans)} agent spans...")

    bound_faithfulness = bind_evaluator(
        evaluator=faithfulness_eval,
        input_mapping={
            "input":   "attributes.input.value",
            "output":  "attributes.output.value",
            "context": "tool_context",
        }
    )

    with suppress_tracing():
        faithfulness_results = evaluate_dataframe(
            agent_spans.set_index('context.span_id'), [bound_faithfulness]
        )

    _log_results(client, faithfulness_results, "faithfulness_score", "faithfulness")

    # --- Tool invocation: did the agent call search_kroger_products sensibly? ---
    if not tool_spans.empty:
        # Bring the user query from the parent agent span into each tool span via trace_id
        agent_inputs = (
            agent_spans[['context.trace_id', 'attributes.input.value']]
            .rename(columns={'attributes.input.value': 'user_query'})
        )
        eval_tool_spans = tool_spans.merge(agent_inputs, on='context.trace_id', how='left')
        eval_tool_spans['available_tools'] = KROGER_TOOL_SCHEMA
        eval_tool_spans['tool_selection'] = (
            eval_tool_spans['name'].fillna('search_kroger_products')
            + '('
            + eval_tool_spans['attributes.input.value'].fillna('').astype(str)
            + ')'
        )

        print(f"Running tool invocation evals on {len(eval_tool_spans)} tool spans...")

        bound_tool_inv = bind_evaluator(
            evaluator=tool_invocation_eval,
            input_mapping={
                "input":           "user_query",
                "available_tools": "available_tools",
                "tool_selection":  "tool_selection",
            }
        )

        with suppress_tracing():
            tool_results = evaluate_dataframe(
                eval_tool_spans.set_index('context.span_id'), [bound_tool_inv]
            )

        _log_results(client, tool_results, "tool_invocation_score", "tool_invocation")


if __name__ == "__main__":
    print("Welcome to your local grocery assistant! Type 'exit' to quit.")

    try:
        while True:
            user_input = input("\nYou: ")
            if user_input.lower() in ['exit', 'quit']:
                print("Exiting Grocery Assistant. Goodbye!")
                break
            try:
                response = agent(user_input)
                print(f"\nAgent: {response}")
            except Exception as e:
                print(f"\nAgent Error: Whoops, something went wrong. ({e})")
    finally:
        print("\nFlushing traces to Arize...")
        provider.force_flush()
        provider.shutdown()

        print("Running evals...")
        run_evals()
