from dotenv import load_dotenv
import os
load_dotenv()

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
from phoenix.evals.metrics import FaithfulnessEvaluator
from phoenix.evals import bind_evaluator, evaluate_dataframe
from phoenix.evals.utils import to_annotation_dataframe
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
    model="gpt-oss:120b-cloud",
    client="openai",
    base_url="https://ollama.com/v1",
    api_key=os.getenv("OLLAMA_API_KEY")
)
faithfulness_eval = FaithfulnessEvaluator(llm=llm)

model = OllamaModel(
    model_id="gpt-oss:120b-cloud",
    host="https://ollama.com"
)

system_prompt = "You are a grocery shopping agent. Please prioritize the users preferences."

agent = Agent(
    model=model,
    tools=[tools.kroger_products.search_kroger_products],
    system_prompt=system_prompt,
    #trace_attributes={
    #    "user.id": "local-tester@domain.com",
    #    "arize.tags": ["local-test", "strands-sdk"]
   # }
)

def run_faithfulness_evals():
    """Pull spans from Phoenix, join tool outputs as context, run faithfulness evals."""
    client = Client(base_url="http://localhost:6006")
    spans_df = client.spans.get_spans_dataframe(project_identifier="weekly-shop")

    if spans_df.empty:
        print("No spans found.")
        return

    agent_spans = spans_df[spans_df['span_kind'] == 'AGENT'].copy()
    tool_spans = spans_df[spans_df['span_kind'] == 'TOOL'].copy()

    if agent_spans.empty:
        print("No agent spans found to evaluate.")
        return

    # Join tool outputs onto agent spans by trace_id so faithfulness has real context
    # Each agent span gets the concatenated output of all tool calls in the same trace
    if not tool_spans.empty:
        tool_context = (
            tool_spans
            .groupby('context.trace_id')['attributes.output.value']
            .apply(lambda outputs: "\n\n".join(str(o) for o in outputs if o))
            .reset_index()
            .rename(columns={'attributes.output.value': 'tool_context'})
        )
        agent_spans = agent_spans.merge(tool_context, on='context.trace_id', how='left')
        agent_spans['tool_context'] = agent_spans['tool_context'].fillna(
            agent_spans['attributes.output.value']  # fallback to output if no tool calls
        )
        context_col = 'tool_context'
    else:
        # No tool calls in these traces — fall back to output as context
        agent_spans['tool_context'] = agent_spans['attributes.output.value']
        context_col = 'tool_context'

    print(f"Evaluating {len(agent_spans)} agent spans...")

    bound_evaluator = bind_evaluator(
        evaluator=faithfulness_eval,
        input_mapping={
            "input": "attributes.input.value",
            "output": "attributes.output.value",
            "context": context_col,
        }
    )

    with suppress_tracing():
        results_df = evaluate_dataframe(agent_spans, [bound_evaluator])

    print(results_df[["label", "score", "explanation"]].head())

    evaluations = to_annotation_dataframe(dataframe=results_df)
    client.spans.log_span_annotations_dataframe(dataframe=evaluations)
    print("Evals logged — check http://localhost:6006")

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
        #Flush traces to Phoenix
        print("\nFlushing traces to Arize...")
        provider.force_flush()
        provider.shutdown()

        #Run span evals
        print("Running faithfulness evals...")
        run_faithfulness_evals()

