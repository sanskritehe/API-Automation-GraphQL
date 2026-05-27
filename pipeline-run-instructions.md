# MCP Pipeline - Run Instructions
_Last updated: 2026-03-23_

---

## Folder Structure

```
Documents/MCP/MCP/
├── jira-mcp-server/          Node.js MCP server → Claude Desktop
├── confluence-mcp-server/    Node.js MCP server → Claude Desktop
├── github-mcp-server/        Node.js MCP server → Claude Desktop
└── orchestrator/             Python pipeline (standalone, no Claude Desktop needed)
    ├── pipeline.py           ← FULL pipeline entry point
    ├── orchestrator.py       ← Copilot only loop (can run standalone too)
    ├── api_clients/
    │   ├── jira.py           calls Jira REST API
    │   ├── confluence.py     calls Confluence REST API
    │   └── github.py         calls GitHub REST API
    ├── app/                  FastAPI service skeleton Copilot edits into
    ├── .env                  all credentials (do not commit)
    ├── .env.example          credential template
    └── requirements.txt
```

---

## Option A — Full Automated Pipeline (recommended)

Runs everything from a Jira ticket key: fetches ticket, fetches Confluence spec,
generates code with Copilot, evaluates with Copilot, opens a GitHub PR.

### 1. Install Python dependencies

```bash
cd Documents/MCP/MCP/orchestrator
pip install -r requirements.txt
```

### 2. Verify .env is populated

All credentials are already in `.env`. Check that they are still valid:
- `JIRA_API_TOKEN` — Atlassian API token
- `CONFLUENCE_API_TOKEN` — Atlassian API token
- `GITHUB_TOKEN` — GitHub PAT (repo + PR permissions)
- `COPILOT_GITHUB_TOKEN` — GitHub PAT with "Copilot Requests" permission
- `GOOGLE_API_KEY` — Google Generative AI API key

### 3. Run the pipeline

```bash
python pipeline.py \
  --ticket KAN-1 \
  --confluence-space hpe-team2 \
  --confluence-page "Appointment Service API Spec" \
  --repo VirajShankar/appointment-service
```

**What happens:**
1. Fetches Jira ticket KAN-1
2. Fetches the Confluence page
3. Builds `prompt.md` locally
4. Creates branch `feature/kan-1` on GitHub and commits `prompt.md`
5. Runs Copilot code generation → Copilot evaluation loop (up to 3 iterations)
6. Commits `generated_solution.md` to the branch
7. Opens a PR → prints the PR URL

---

## Option B — Orchestrator Only (if you already have a prompt.md)

If `prompt.md` already exists in the `orchestrator/` directory:

```bash
cd Documents/MCP/MCP/orchestrator
python orchestrator.py
```

Output: `generated_solution.md`

---

## Option C — Claude Desktop via MCP Servers

For interactive use through Claude Desktop (manual, step-by-step).

### 1. Register MCP servers

File: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "jira": {
      "command": "node",
      "args": ["C:/Users/viraj/Documents/MCP/MCP/jira-mcp-server/server.js"]
    },
    "confluence": {
      "command": "node",
      "args": ["C:/Users/viraj/Documents/MCP/MCP/confluence-mcp-server/server.js"]
    },
    "github": {
      "command": "node",
      "args": ["C:/Users/viraj/Documents/MCP/MCP/github-mcp-server/server.js"]
    }
  }
}
```

Restart Claude Desktop after saving.

### 2. Paste this prompt into Claude Desktop

```
Run the pipeline for Jira ticket <ISSUE-KEY>:

1. Use get_jira_issue to fetch the ticket
2. Use get_confluence_page (spaceKey: hpe-team2, title: <page title>) to fetch the API spec
3. Check for ambiguities — list them if any, otherwise proceed
4. Generate prompt.md from Jira requirements + Confluence spec
5. Use create_branch to create feature/<issue-key> from main in repo <repo>
6. Use update_file to commit prompt.md to that branch
7. Use create_pr to open a PR from the feature branch into main
```

---

## Sanity Check — MCP servers

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ping","arguments":{}}}' \
  | node Documents/MCP/MCP/jira-mcp-server/server.js
```

Expected: `{"status":"pong",...}`

---

## Full Pipeline Flow

```
Developer creates Jira ticket
        │
        ▼
pipeline.py fetches ticket via Jira REST API
        │
        ▼
pipeline.py fetches API spec via Confluence REST API
        │
        ▼
Builds prompt.md  ──→  commits to feature branch on GitHub
        │
        ▼
orchestrator.py sends prompt to GitHub Copilot (gpt-4o)
        │
        ▼
Copilot judge (gpt-4o) evaluates generated code
   rejected? ──→ feedback fed back to Copilot (max 3 retries)
   approved?  ──→ commit generated_solution.md to branch
        │
        ▼
GitHub PR opened automatically
        │
        ▼
CI guard: static analysis, unit tests, contract tests, regression, fuzz, mutation
```
