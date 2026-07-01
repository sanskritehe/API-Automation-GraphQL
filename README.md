# HPE AI-Assisted GraphQL Automation Platform

An end-to-end agentic development pipeline that converts Jira tickets into production-ready GraphQL microservice code — automatically generating, validating, composing, and deploying Pull Requests across a federated microservice architecture.

---

## How It Works

A Jira ticket assignment fires a webhook. The pipeline fetches the spec from Confluence, generates FastAPI code using an LLM, validates it through two correction layers, composes the GraphQL supergraph, and opens parallel PRs across all affected repos — then posts the PR links back to Jira.

```mermaid
flowchart TD
    %% ── Trigger ──────────────────────────────────────────────
    A([Jira Ticket Assigned]) -->|Issue Updated event| B[ngrok Tunnel\nport 8000]
    B -->|POST /webhook| C[webhook_server.py\nFastAPI]

    %% ── Pipeline Orchestration ────────────────────────────────
    C -->|Spawns subprocess| D[pipeline.py]
    D -->|Fetch API spec| E[(Confluence Wiki)]
    D -->|Detect method + keyword\nservice_groups.json| F{Route to repos}

    %% ── Agentic Loop ──────────────────────────────────────────
    F -->|Build prompt.md| G[orchestrator.py]

    subgraph LOOP ["Self-Correcting Generation Loop  (max 3 retries)"]
        direction TB
        G1[Generator LLM\ngpt-4o-mini] -->|writes code| G2

        subgraph L1 ["Layer 1 — Static Checks"]
            G2[py_compile] --> G3[ruff] --> G4[mypy] --> G5[bandit]
        end

        G5 -->|Fail → inject errors into prompt| G1
        G5 -->|Pass| G6

        subgraph L2 ["Layer 2 — LLM Judge"]
            G6[Judge LLM\ngpt-4o-mini\nJSON rubric evaluation]
        end

        G6 -->|Reject → inject feedback into prompt| G1
    end

    %% ── Post-approval ─────────────────────────────────────────
    G6 -->|Approve| H[Sync code to\nlocal service folders]
    H --> I[compose.py\nApollo Rover via WSL\ncompiles supergraph]
    I --> J[asyncio.gather\nParallel fan-out]

    J -->|api role| K[Appointment-Service PR]
    J -->|database role| L[Appointment-Database-Service PR]
    J -->|gateway role| M[rest-api-gateway PR]
    J -->|graphql role| N[graphql-datagraph PR\n.graphql schemas only]

    K & L & M & N --> O([PR URLs posted to Jira])

  
    end
```

---

## Repository Layout

| Directory | Role | Responsibility |
| :--- | :--- | :--- |
| `API-Automation-GraphQL` | **Pipeline Engine** | `webhook_server.py`, `pipeline.py`, `orchestrator.py`, prompt templates, `service_groups.json` |
| `graphql-datagraph` | **Schema Registry & Gateway** | Apollo Router config, `compose.py` (Rover supergraph compilation) |
| `Appointment-Service` | **Business Logic Subgraph** | FastAPI service — appointment rules, validation, GraphQL resolvers (:8001) |
| `Appointment-Database-Service` | **Database Subgraph** | FastAPI service — SQLAlchemy + SQLite data access layer (:8000) |
| `rest-api-gateway` | **REST Proxy** | Translates incoming REST calls into GraphQL queries against the Apollo Router (:8080) |

---

## Pipeline Components

### `webhook_server.py`
FastAPI server listening on port 8000. Filters incoming Jira events by assignee (`COPILOT_ASSIGNEE` env var) and service keyword. Uses an `active_runs` set to prevent duplicate pipeline executions for the same ticket. Fires `pipeline.py` as a background subprocess so Jira gets an immediate `202 accepted` response.

### `pipeline.py`
The main orchestration entry point. Fetches Jira ticket fields and the Confluence API spec, detects the HTTP method and service keyword from ticket text, builds `prompt.md` (template + Jira + Confluence), calls the orchestrator once, then fans out to all matched repos in parallel via `asyncio.gather`.

### `orchestrator.py`
The self-correcting generation loop. Reads all existing `app/` Python files as context, generates code via the generator LLM, runs two sequential validation layers, and loops up to 3 times before raising. Supports Gemini, Groq, or GitHub Models as the backend — provider is resolved from env vars at startup.

### `service_groups.json`
Static routing config. Maps service keywords (`appointment`, `patient`, `billing`) to repo lists with role labels and allowed HTTP methods. Determines which repos receive PRs and whether GraphQL schema composition runs.

---

## Two-Layer Validation

Every generated code output passes through two sequential layers before a PR is opened:

**Layer 1 — Static Analysis** (deterministic, runs locally)
1. `py_compile` — syntax errors. Blocks further checks if found.
2. `ruff` — style and import errors (auto-fixed before checking)
3. `mypy` — type errors
4. `bandit` — security issues (medium severity and above)

**Layer 2 — LLM Judge** (probabilistic, runs only if Layer 1 passes)

The judge LLM receives the full generated codebase and the original requirements. It responds with a strict JSON object:
```json
{ "met_conditions": true, "feedback": "" }
```
On rejection, the feedback string is injected back into the next iteration's prompt. On approval, the pipeline proceeds to schema composition and deployment.

---

## Repo Routing Logic

The HTTP method detected from the ticket text determines which repos receive PRs:

| Ticket Method | Repos Targeted | compose.py runs? |
| :--- | :--- | :--- |
| GET / POST / PUT / PATCH / DELETE | api + database + gateway (3 repos) | No |
| QUERY / MUTATION | api + database + gateway + graphql (4 repos) | Yes |

GraphQL method detection checks for the literal phrase `"graphql query"` or `"graphql"` + `"query"` in the ticket summary and description before falling back to REST keyword matching.

---

## Running the Pipeline

### 1. Start the webhook server
```bash
cd API-Automation-GraphQL
python orchestrator/webhook_server.py
```

### 2. Expose it publicly via ngrok
```bash
ngrok http 8000
```
Copy the generated `*.ngrok-free.dev` URL.

### 3. Register the webhook in Jira
Go to **Project Settings → System → Webhooks → Create Webhook**.
Paste the ngrok URL with `/webhook` appended:
```
https://your-tunnel.ngrok-free.dev/webhook
```
Set the trigger to **Issue Updated**.

### 4. Trigger the pipeline
Assign any ticket whose description contains a service keyword (e.g. `appointment`) to the user configured in `COPILOT_ASSIGNEE`. The webhook fires, the pipeline runs in the background, and PR links appear as a Jira comment when complete.

---

## Running the Runtime Environment

```bash
cd graphql-datagraph
docker-compose up --build
```

| Service | URL |
| :--- | :--- |
| REST API Gateway | http://localhost:8080 |
| Apollo Router (GraphQL) | http://localhost:4000 |
| Appointment Service | http://localhost:8001/graphql |
| Appointment Database Service | http://localhost:8000/graphql |

---

## GraphQL Schema Composition

`compose.py` uses Apollo Rover to merge the two subgraph schemas into a unified supergraph. On Windows, if Application Control Policies block the Rover binary, `compose.py` automatically redirects the compilation command to a local **WSL Ubuntu** instance to complete the build.

Composed schema files staged to the orchestrator directory for deployment:
- `supergraph.graphql`
- `appointment-service.graphql`
- `appointment-database-service.graphql`

---

## Environment Variables

| Variable | Used in | Purpose |
| :--- | :--- | :--- |
| `GITHUB_TOKEN` | `orchestrator.py`, `github.py` | GitHub Models API auth + repo operations |
| `GENERATOR_MODEL` | `orchestrator.py` | LLM model for code generation (default: `gpt-4o-mini`) |
| `JUDGE_MODEL` | `orchestrator.py` | LLM model for evaluation (default: `gpt-4o-mini`) |
| `JIRA_DOMAIN` | `jira.py` | Your Jira Cloud base URL |
| `JIRA_EMAIL` | `jira.py` | Jira account email |
| `JIRA_API_TOKEN` | `jira.py` | Jira API token |
| `CONFLUENCE_DOMAIN` | `confluence.py` | Your Confluence Cloud base URL |
| `CONFLUENCE_EMAIL` | `confluence.py` | Confluence account email |
| `CONFLUENCE_API_TOKEN` | `confluence.py` | Confluence API token |
| `COPILOT_ASSIGNEE` | `webhook_server.py` | Jira username/email that triggers the pipeline |
| `CONFLUENCE_SPACE` | `webhook_server.py` | Default Confluence space key |
| `CONFLUENCE_PAGE` | `webhook_server.py` | Default Confluence page title |
