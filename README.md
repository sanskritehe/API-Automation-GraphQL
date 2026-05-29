# AI-Assisted API Automation Pipeline

An end-to-end pipeline that takes a Jira ticket, pulls the matching API spec from Confluence, generates FastAPI implementation code using an AI model loop, and opens pull requests in your GitHub repos — then comments the PR links back on the ticket.

It's built for FastAPI services that follow a layered structure:

```
routes → services → db_client
```

---

## How It Works

1. A Jira ticket is assigned to the automation user
2. The webhook server picks it up (or you run the pipeline manually)
3. The pipeline fetches the ticket details and the API spec from Confluence
4. It detects the HTTP method and service name from the ticket text
5. It picks the right GitHub repos from `service_groups.json`
6. It builds a `prompt.md` from the method template + ticket + spec, then runs a generate → judge loop
7. It creates a branch, commits the generated files, and opens a PR in each matched repo
8. It posts the PR links as a comment on the Jira ticket

---

## Project Structure

```
MCP/
├── jira-mcp-server/           Node.js MCP server for Jira
├── confluence-mcp-server/     Node.js MCP server for Confluence
├── github-mcp-server/         Node.js MCP server for GitHub
└── orchestrator/
    ├── pipeline.py            Main entry point — runs the full pipeline
    ├── orchestrator.py        Generation + judge loop only
    ├── webhook_server.py      FastAPI webhook listener for Jira events
    ├── service_groups.json    Maps service keywords → GitHub repos
    ├── api_clients/
    │   ├── jira.py
    │   ├── confluence.py
    │   └── github.py
    ├── prompts/               Local fallback prompt templates (GET/POST/etc.)
    ├── app/                   Where generated code gets written
    ├── .env                   All credentials go here
    └── requirements.txt
```

---

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- [ngrok](https://ngrok.com) account (free tier works) — only needed for the webhook

### Credentials You'll Need

Before setting up the `.env`, make sure you have the following ready:

**Jira**
- Your Jira domain: `https://your-org.atlassian.net`
- Your Jira account email
- A Jira API token → [generate one here](https://id.atlassian.com/manage-profile/security/api-tokens)

**Confluence**
- Same domain and email as Jira (usually)
- A Confluence API token (can be the same token)
- The space key for your Confluence space — visible in the URL: `.../wiki/spaces/SPACEKEY`
- The exact title of the page that contains your API spec

**GitHub**
- A personal access token with `repo` and `workflow` scopes → [generate here](https://github.com/settings/tokens)
- Your GitHub org or username

**AI Model — pick one**

| Option | Where to get the key | Notes |
|--------|----------------------|-------|
| Groq (recommended) | [console.groq.com](https://console.groq.com) | Free tier, fast |
| OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) | Requires paid plan |

---

## Setup

### 1. Install Node dependencies

```bash
cd jira-mcp-server && npm install
cd ../confluence-mcp-server && npm install
cd ../github-mcp-server && npm install
```

### 2. Install Python dependencies

```bash
cd ../orchestrator
pip install -r requirements.txt
```

### 3. Create the `.env` file

Create `orchestrator/.env` and fill in your credentials:

```dotenv
# ── Jira ──────────────────────────────────────────────────────────────
JIRA_DOMAIN=https://your-org.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your_jira_api_token

# ── Confluence ────────────────────────────────────────────────────────
CONFLUENCE_DOMAIN=https://your-org.atlassian.net
CONFLUENCE_EMAIL=your-email@company.com
CONFLUENCE_API_TOKEN=your_confluence_api_token
CONFLUENCE_SPACE=~your_confluence_space_key
CONFLUENCE_PAGE=Your API Spec Page Title

# ── GitHub ────────────────────────────────────────────────────────────
GITHUB_TOKEN=ghp_your_token_here
GITHUB_OWNER=your-org-or-username
BASE_BRANCH=main

# ── Prompt templates (fetched from GitHub at runtime) ─────────────────
PROMPTS_REPO=your-org/your-repo
PROMPTS_BRANCH=main

# ── AI model ──────────────────────────────────────────────────────────
# Groq:
GROQ_API_KEY=gsk_your_groq_key
GENERATOR_MODEL=llama-3.3-70b-versatile
JUDGE_MODEL=llama-3.3-70b-versatile

# OpenAI (alternative):
# OPENAI_API_KEY=sk-proj-your_key
# GENERATOR_MODEL=gpt-3.5-turbo
# JUDGE_MODEL=gpt-3.5-turbo

# ── Webhook filter (optional) ─────────────────────────────────────────
# Only trigger the pipeline when a ticket is assigned to this user.
# Leave empty to trigger on any assignment.
COPILOT_ASSIGNEE=automation-bot@company.com
```

---

## Connecting to Your Codebase

The pipeline routes tickets to repos using `orchestrator/service_groups.json`. Each entry maps a keyword (detected from the ticket text) to one or more GitHub repos.

```json
{
  "appointment": [
    {
      "repo": "your-org/Appointment-Service",
      "role": "api",
      "operations": ["GET", "POST", "PUT", "PATCH", "DELETE"]
    },
    {
      "repo": "your-org/Appointment-DB-Service",
      "role": "database",
      "operations": ["GET", "POST", "PUT", "PATCH", "DELETE"]
    }
  ],
  "patient": [
    {
      "repo": "your-org/Patient-Service",
      "role": "api",
      "operations": ["GET", "POST", "PUT", "PATCH"]
    }
  ]
}
```

To add a new service:

1. Add an entry to `service_groups.json` with a keyword and target repo(s)
2. Make sure the GitHub token has push access to those repos
3. Confirm the repos follow the `routes → services → db_client` structure (or update the prompt templates to match your structure)

The keyword is auto-detected from the Jira ticket text. If detection fails, you can pass it manually with `--keyword`.

---

## Running the Pipeline

### Manual run

```bash
cd orchestrator

python pipeline.py \
  --ticket KAN-1 \
  --confluence-space ~your_space_key \
  --confluence-page "Your API Spec Page Title" \
  --keyword appointment \
  --base-branch main
```

### Test generation only (no GitHub, no Jira)

If `prompt.md` already exists in `orchestrator/`, you can test just the AI loop:

```bash
cd orchestrator
python orchestrator.py
```

Outputs: `generated_solution.md` and `app/`

---

## Running the Webhook Server

The webhook server listens for Jira issue updates and triggers the pipeline automatically when a ticket is assigned.

### 1. Start the server

```bash
cd orchestrator
python webhook_server.py
```

It runs on `http://localhost:8000`. Check it's up:

```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

### 2. Expose it with ngrok

In a separate terminal:

```bash
ngrok http 8000
```

Copy the HTTPS URL it gives you — something like `https://abcd-1234.ngrok-free.app`.

### 3. Register the webhook in Jira

1. Go to **Jira Settings → System → Webhooks**
2. Create a new webhook
3. Set the URL to `https://your-ngrok-url.ngrok-free.app/webhook`
4. Select the **Issue updated** event
5. Save

### 4. Trigger it

Assign a Jira ticket to the user set in `COPILOT_ASSIGNEE` (or any user if that's left empty). The ticket summary or description must contain a keyword from `service_groups.json`.

The terminal running `webhook_server.py` will show the full pipeline progress.

---

## Prompt Templates

The pipeline fetches method-specific templates from the repo set in `PROMPTS_REPO`:

```
prompts/GET.md
prompts/POST.md
prompts/PUT.md
prompts/PATCH.md
prompts/DELETE.md
```

It combines the right template with the live Jira ticket data and Confluence spec to build `prompt.md` at runtime. If the remote fetch fails, it falls back to a basic built-in template.

You can override or customize templates by editing the files in your `PROMPTS_REPO`.

---

## Troubleshooting

**`ignored: no assignee set`** — Assign the ticket before triggering the webhook.

**`ignored: assignee is not the copilot agent`** — Either update `COPILOT_ASSIGNEE` in `.env` or assign the ticket to the configured automation user.

**`ignored: no matching service keyword found`** — Add the service keyword to `service_groups.json`, or pass `--keyword your-keyword` manually.

**`404` on Confluence** — Double-check the space key and page title (case-sensitive). You can find the space key in the Confluence URL: `.../wiki/spaces/SPACEKEY`.

**GitHub auth errors** — Regenerate your token at https://github.com/settings/tokens. It needs `repo` and `workflow` scopes.

**ngrok URL expired** — Free ngrok URLs change on restart. Update the Jira webhook URL whenever you restart ngrok.

**Generated code doesn't match your repo structure** — Update the prompt templates in `PROMPTS_REPO` to reflect your architecture, or manually adjust the generated PR.

---

## Claude Desktop (Optional — for manual tool testing)

You can register the MCP servers with Claude Desktop to test Jira/Confluence/GitHub tools manually.

Config file location:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "jira": {
      "command": "node",
      "args": ["/absolute/path/to/MCP/jira-mcp-server/server.js"]
    },
    "confluence": {
      "command": "node",
      "args": ["/absolute/path/to/MCP/confluence-mcp-server/server.js"]
    },
    "github": {
      "command": "node",
      "args": ["/absolute/path/to/MCP/github-mcp-server/server.js"]
    }
  }
}
```

Restart Claude Desktop after saving.
