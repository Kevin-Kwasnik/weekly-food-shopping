# Weekly Food Shopping Agent

An AI-powered grocery shopping assistant built with the [Strands Agents SDK](https://github.com/strands-ai/strands), backed by the Kroger API, with full OpenTelemetry tracing and LLM-as-a-judge correctness evals via [Arize Phoenix](https://arize.com/docs/phoenix).

---

## Project Structure

```
weekly-food-shopping/
├── src/
│   ├── agent.py                  # Main agent entrypoint
│   ├── tools/
│   │   └── kroger_products.py    # Kroger product search tool
│   └── utils/
│       └── kroger_helper.py      # Kroger OAuth token helper
├── .env                          # Environment variables (not committed)
├── .env.example                  # Example env file
└── README.md
```

---

## Features

- **Conversational grocery assistant** — natural language shopping via Ollama Cloud
- **Kroger API integration** — searches real product catalog with pricing and UPC
- **OpenTelemetry tracing** — every agent call, LLM invocation, and tool call traced
- **Arize Phoenix observability** — traces visible at `http://localhost:6006`
- **Faithfulness evals** — detects hallucinated products or prices not grounded in actual Kroger results
- **Tool invocation evals** — validates that `search_kroger_products` was called with sensible arguments

---

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager
- An [Ollama Cloud](https://ollama.com) account and API key
- A [Kroger Developer](https://developer.kroger.com) app (client ID + secret)

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/weekly-food-shopping.git
cd weekly-food-shopping
uv sync
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
# Kroger API
KROGER_CLIENT_ID=your_kroger_client_id
KROGER_CLIENT_SECRET=your_kroger_client_secret

# Ollama Cloud (used for the agent model and eval judge)
OLLAMA_API_KEY=your_ollama_api_key
```

### 3. Start Phoenix locally

Phoenix is used to collect and visualise traces. Start it in a separate terminal before running the agent:

```bash
# Install Phoenix if not already installed
uv add arize-phoenix

# Option A — CLI (recommended for local development)
phoenix serve
# Phoenix UI available at http://localhost:6006

# Option B — Docker
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest
```

> Phoenix persists traces in-memory by default. For persistent storage across restarts, see [Self-Hosting](https://arize.com/docs/phoenix/self-hosting).

#### Phoenix Environments

| Environment | How to run | Best for |
|---|---|---|
| **Terminal** | `phoenix serve` | Local development |
| **Docker** | `docker run arizephoenix/phoenix` | Persistent / team use |
| **Phoenix Cloud** | [app.phoenix.arize.com](https://app.phoenix.arize.com) | Managed, no setup |

---

## Running the Agent

```bash
uv run src/agent.py
```

You'll see:

```
Welcome to your local grocery assistant! Type 'exit' to quit.

You: chicken breast
Agent: I found some chicken options for you! Here are the top results...

You: exit
Exiting Grocery Assistant. Goodbye!

Flushing traces to Arize...
Running evals...
Running faithfulness evals on 3 agent spans...
  -> faithfulness annotations logged — check http://localhost:6006
Running tool invocation evals on 3 tool spans...
  -> tool_invocation annotations logged — check http://localhost:6006
```

---

## Observability

### Traces

Every session automatically sends traces to your local Phoenix instance. Open `http://localhost:6006` to see:

- **Agent spans** — top-level invocations with input/output
- **LLM spans** — model calls with token counts and latency
- **Tool spans** — Kroger API calls with search terms and results

Traces follow the [OpenInference](https://github.com/Arize-ai/openinference) semantic conventions, compatible with Arize AX and any OTLP-compatible backend.

### Evals

Two LLM-as-a-judge evaluations run automatically at the end of each session, using an Ollama Cloud model as the judge.

**Faithfulness** (on agent spans) — checks whether the agent's response is grounded in what `search_kroger_products` actually returned, detecting hallucinated product names, prices, or UPCs.

**Tool Invocation** (on tool spans) — checks whether `search_kroger_products` was called with sensible arguments given the user's query (e.g. reasonable search terms, no hallucinated parameters).

Both results are logged back to Phoenix as span annotations (`faithfulness`, `tool_invocation`) and visible alongside traces in the UI.

To change the eval judge model, update the `LLM` config in `src/agent.py`:

```python
llm = LLM(
    provider="openai",
    model="qwen3-coder-next:cloud",
    client="openai",
    base_url="https://ollama.com/v1",
    api_key=os.getenv("OLLAMA_API_KEY"),
)
```

---

## Architecture

```
User input
    │
    ▼
Strands Agent  ──────────────────────────────────────────────────►  OTel Traces
    │                                                                      │
    ▼                                                                      ▼
OllamaModel (gpt-oss:120b-cloud)                              Arize Phoenix :6006
    │                                                                      │
    ▼                                                                      ▼
search_kroger_products tool                            Faithfulness Eval (agent spans)
    │                                                  Tool Invocation Eval (tool spans)
    ▼                                                         (Ollama as judge)
Kroger Certification API
```

---

## Troubleshooting

**Traces not appearing in Phoenix**
Make sure Phoenix is running (`phoenix serve`) before starting the agent. Traces are flushed on exit — you won't see them until you type `exit`.

**Proxy / firewall blocking Arize Cloud**
If you're on a corporate network, use local Phoenix (`phoenix serve`) instead of `otlp.arize.com`. The local setup requires no auth and bypasses proxy restrictions.

**Kroger token errors**
Ensure `KROGER_CLIENT_ID` and `KROGER_CLIENT_SECRET` are set and your app has the `product.compact` scope enabled in the Kroger Developer Portal.

---

## References

- [Strands Agents SDK](https://github.com/strands-ai/strands)
- [Arize Phoenix Docs](https://arize.com/docs/phoenix)
- [Phoenix Environments](https://arize.com/docs/phoenix/environments)
- [OpenInference Semantic Conventions](https://github.com/Arize-ai/openinference)
- [Kroger Developer Portal](https://developer.kroger.com)
- [Ollama Cloud](https://ollama.com)
