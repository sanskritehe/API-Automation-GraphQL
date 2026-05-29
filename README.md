# AI-Assisted API Automation Pipeline

An end-to-end pipeline that turns a Jira ticket into a pull request — automatically.

Given a ticket, it fetches your API spec from Confluence, generates a FastAPI implementation using an LLM judge loop, creates a branch, commits the code, opens a PR in every matching GitHub repo, and posts the PR links back on the Jira ticket.

```
Jira ticket assigned
       │
       ▼
Fetch ticket + Confluence spec
       │
       ▼
Build prompt  →  LLM generates code  →  LLM judges code
                       ↑                      │
                       └── feedback (max 3x) ─┘
                                              │ approved
                                              ▼
                          Create branch → Commit files → Open PR
                                              │
                                              ▼
                              Post PR links as Jira comment
```

---

## Table of Contents

- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Credentials You Will Need](#credentials-you-will-need)
- [Setup](#setup)
- [Configure for Your Repos](#configure-for-your-repos)
- [Set Up Prompt Templates](#set-up-prompt-templates)
- [Verify Your Setup](#verify-your-setup)
- [Running the Pipeline](#running-the-pipeline)
- [Webhook Mode](#webhook-mode)
- [Understanding the Output](#understanding-the-output)
- [Deploying for Your Organization](#deploying-for-your-organization)
- [Claude Desktop — Optional](#claude-desktop--optional)
- [Troubleshooting](#troubleshooting)

---

## How It Works

1. A Jira ticket is assigned to your automation user (or you trigger it manually from the CLI)
2. The pipeline fetches the ticket's summary and description from Jira
3. It fetches the matching API spec page from Confluence
4. It scans the ticket text to detect the HTTP method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) and a service keyword (e.g. `appointment`)
5. It looks up the keyword in `service_groups.json` to find which GitHub repos to target
6. It downloads the matching prompt template from your `PROMPTS_REPO` and combines it with the live Jira and Confluence data to produce `prompt.md`
7. It sends the prompt to Groq's LLM. A second LLM call then judges whether the output meets the requirements. If it does not, the feedback is injected and the model tries again — up to 3 iterations
8. It creates a feature branch in each matched repo, commits `prompt.md`, `generated_solution.md`, and all files in `app/`, and opens a PR
9. It posts all PR URLs as a comment on the original Jira ticket

The pipeline is designed for FastAPI services that follow this three-layer structure:

```
routes/  →  services/  →  db_client.py
```

If your repos use a different structure, you can adapt the prompt templates to match.

---

## Project Structure

```
MCP/
├── jira-mcp-server/            Node.js MCP server — Jira tools for Claude Desktop
├── confluence-mcp-server/      Node.js MCP server — Confluence tools for Claude Desktop
├── github-mcp-server/          Node.js MCP server — GitHub tools for Claude Desktop
└── orchestrator/
    ├── pipeline.py             Main entry point — runs the full pipeline end to end
    ├── orchestrator.py         LLM generate + judge loop only (can run standalone)
    ├── webhook_server.py       FastAPI webhook listener — triggers pipeline from Jira events
    ├── service_groups.json     Maps service keywords → target GitHub repos
    ├── api_clients/
    │   ├── jira.py             Jira REST API client
    │   ├── confluence.py       Confluence REST API client
    │   └── github.py           GitHub REST API client
    ├── prompts/                Reference prompt templates (see Set Up Prompt Templates)
    ├── app/                    FastAPI service skeleton — the LLM writes generated code here
    ├── .env                    Your credentials (never commit this file)
    ├── .env.example            Credential template
    └── requirements.txt
```

> **The `app/` directory** is the FastAPI service skeleton the LLM modifies on each run. It
> currently contains example output from a previous run. You can leave it as-is — the pipeline
> overwrites only the files relevant to each ticket.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Required for the automated pipeline |
| Node.js | 18+ | Only needed for Claude Desktop MCP servers — not required for the automated webhook pipeline |
| npm | bundled with Node.js | Same as above |
| ngrok | any | Only needed for local webhook development. Free tier works. |

---

## Credentials You Will Need

Collect these before starting the `.env` setup.

### Jira
- Your Jira domain: `https://your-org.atlassian.net`
- Your Jira account email
- A Jira API token → [generate one here](https://id.atlassian.net/manage-profile/security/api-tokens)

### Confluence
- Your Confluence domain (usually the same as Jira)
- Your Confluence account email (usually the same as Jira)
- A Confluence API token (can be the same token as Jira)
- Your Confluence **space key** — find it in the URL when browsing your space:
  ```
  https://your-org.atlassian.net/wiki/spaces/SPACEKEY/...
                                                ^^^^^^^^
  ```
  > **Personal spaces** use a tilde prefix with a user ID, like `~712020abc123`. You can find
  > this in the URL when viewing your personal Confluence space. Team and project spaces use a
  > plain key like `DEV` or `ENGINEERING`. Use whichever format matches the space your API spec
  > lives in.
- The **exact title** of the Confluence page that contains your API spec (case-sensitive)

### GitHub
- A personal access token with **`repo` scope** → [generate one here](https://github.com/settings/tokens)
  - Add `workflow` scope too if your repos contain GitHub Actions files
- Your GitHub username or organization name — **only needed if you use the GitHub MCP server with Claude Desktop**. The automated pipeline reads the owner from `service_groups.json` directly (the `"repo"` field uses `owner/repo-name` format) and does not read a `GITHUB_OWNER` env var.

### AI Model

The pipeline currently uses **Groq** as its LLM provider. Get a free API key at [console.groq.com](https://console.groq.com).

> **Want to use OpenAI instead?** The provider is not switchable via config alone — `orchestrator.py`
> hardcodes both the API key variable name (`GROQ_API_KEY`) and the endpoint
> (`https://api.groq.com/openai/v1`). To switch, edit those two lines in `orchestrator.py` to
> use `OPENAI_API_KEY` and `https://api.openai.com/v1` respectively.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-org/your-fork.git
cd MCP
```

### 2. Create `.env`

```bash
cp orchestrator/.env.example orchestrator/.env
```

Open `orchestrator/.env` and fill in your values:

```bash
# ── Jira ──────────────────────────────────────────────────────────────
JIRA_DOMAIN=https://your-org.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_jira_api_token

# ── Confluence ────────────────────────────────────────────────────────
CONFLUENCE_DOMAIN=https://your-org.atlassian.net
CONFLUENCE_EMAIL=you@company.com
CONFLUENCE_API_TOKEN=your_confluence_api_token

# These two are used by the WEBHOOK SERVER only.
# When running pipeline.py manually, pass --confluence-space and --confluence-page as CLI args instead.
# Space key examples:
#   Team space:     CONFLUENCE_SPACE=ENGINEERING
#   Personal space: CONFLUENCE_SPACE=~712020abc123def456
CONFLUENCE_SPACE=your_space_key
CONFLUENCE_PAGE=Your API Spec Page Title

# ── GitHub ────────────────────────────────────────────────────────────
GITHUB_TOKEN=ghp_your_token_here
# Note: the pipeline reads the owner from service_groups.json (owner/repo format).
# GITHUB_OWNER is only needed if you use the GitHub MCP server with Claude Desktop.
# GITHUB_OWNER=your-org-or-username
BASE_BRANCH=main

# ── Prompt templates ──────────────────────────────────────────────────
# Set this to a repo YOU own that contains prompts/GET.md, POST.md, etc.
# See "Set Up Prompt Templates" below.
PROMPTS_REPO=your-org/your-repo
PROMPTS_BRANCH=main

# ── AI model ──────────────────────────────────────────────────────────
# Groq is the only supported provider out of the box.
# Get a free key at console.groq.com
GROQ_API_KEY=gsk_your_groq_key
GENERATOR_MODEL=llama-3.3-70b-versatile
JUDGE_MODEL=llama-3.3-70b-versatile

# ── Webhook filter ────────────────────────────────────────────────────
# Only trigger the pipeline when a ticket is assigned to this email.
# Leave empty to trigger on any assignment.
COPILOT_ASSIGNEE=automation-bot@company.com
```

> **Important:** `orchestrator/.env` is listed in `.gitignore`. Never commit this file.

### 3. Install Python dependencies

```bash
cd orchestrator
python -m venv venv

# macOS / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate

pip install -r requirements.txt
```

### 4. Install Node.js dependencies *(Claude Desktop only)*

> **Skip this step if you only want the automated webhook pipeline.** The Node.js MCP servers are
> only used with Claude Desktop for interactive, conversational access to Jira, Confluence, and
> GitHub. They are not involved in the automated pipeline flow at all.

```bash
cd ../jira-mcp-server && npm install
cd ../confluence-mcp-server && npm install
cd ../github-mcp-server && npm install
```

### 5. Protect your credentials from git

`orchestrator/.gitignore` covers `orchestrator/.env`, but the MCP server `.env` files are **not** gitignored by default. If you plan to push this repo, create a root-level `.gitignore` now:

```bash
# run from the repo root (MCP/)
cat >> .gitignore << 'EOF'
jira-mcp-server/.env
confluence-mcp-server/.env
confluence-mcp-server/env
github-mcp-server/.env
.vscode/mcp.json
EOF
```

---

## Configure for Your Repos

`orchestrator/service_groups.json` is the routing table that tells the pipeline which GitHub repos to open PRs in, based on the service keyword found in the Jira ticket.

Open it and replace the example entries with your own:

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

**How it works:**

- The **key** (`"appointment"`, `"patient"`) is the keyword the pipeline scans for in the Jira ticket summary and description. Make it a word that will naturally appear in your tickets.
- Each entry under a key is a GitHub repo that will receive a PR when that keyword is detected.
- **`repo`** is `owner/repo-name` — must match exactly what appears in the GitHub URL.
- **`role`** is a label used in the PR title and Jira comment to distinguish between repos (e.g. `"api"` vs `"database"`). Pick any label that makes sense to your team.
- **`operations`** lists which HTTP methods are allowed for this repo. A PATCH ticket for `appointment` will only open PRs in repos that include `"PATCH"` in their operations list.

**To add a new service:**

1. Add a new key to `service_groups.json` with your repo(s)
2. Make sure the `GITHUB_TOKEN` has push access to those repos
3. Ensure those repos follow a `routes → services → db_client` structure, or update your prompt templates to match your actual structure

**If keyword detection fails:**

The pipeline scans ticket text automatically. If it cannot find a match, it exits with a message listing the available keywords. You can always bypass detection with the `--keyword` flag:

```bash
python pipeline.py --ticket PROJ-42 ... --keyword patient
```

---

## Set Up Prompt Templates

The pipeline fetches method-specific templates from the GitHub repo you set in `PROMPTS_REPO`. It looks for these files:

```
prompts/GET.md
prompts/POST.md
prompts/PUT.md
prompts/PATCH.md
prompts/DELETE.md
```

These templates are combined with the live Jira ticket data and Confluence spec to build the final prompt. The quality of generated code depends directly on how well your templates describe your repo's architecture.

**To set this up:**

1. Create a `prompts/` directory in any GitHub repo you own (it can be one of your service repos or a dedicated config repo)
2. Add one `.md` file per HTTP method. You can use the `PATCH.md` in `orchestrator/prompts/` as a reference for structure
3. Each template should describe:
   - The architecture pattern your service follows
   - The exact file paths to create or modify
   - The expected request and response formats
   - Any validation or error handling rules specific to your codebase
4. Set `PROMPTS_REPO=your-org/your-repo` in `orchestrator/.env`

> **If `PROMPTS_REPO` is not set or the repo is not accessible**, the pipeline falls back to a
> minimal 2-line placeholder prompt. The pipeline will not error — but the generated code will be
> generic and unlikely to match your codebase. Always configure this before running the pipeline
> for real.

---

## Verify Your Setup

Before running a full pipeline run, check that each integration is reachable. Run these from inside `orchestrator/` with your venv active:

```bash
# Check Jira
python -c "
from api_clients.jira import get_jira_issue
t = get_jira_issue('YOUR-TICKET-KEY')
print('Jira OK:', t['summary'])
"

# Check Confluence
python -c "
from api_clients.confluence import get_confluence_page
p = get_confluence_page('YOUR_SPACE_KEY', 'Your Page Title')
print('Confluence OK:', p['title'])
"

# Check GitHub
python -c "
from api_clients.github import get_file
content = get_file('your-org/your-repo', 'README.md')
print('GitHub OK — README length:', len(content))
"
```

Each should print a confirmation. Fix any that fail before proceeding.

---

## Running the Pipeline

### Manual run — full pipeline

```bash
cd orchestrator
python pipeline.py \
  --ticket YOUR-TICKET-KEY \
  --confluence-space YOUR_SPACE_KEY \
  --confluence-page "Your API Spec Page Title" \
  --base-branch main
```

The `--keyword` flag is optional. If not provided, the pipeline detects it from the ticket text:

```bash
python pipeline.py \
  --ticket YOUR-TICKET-KEY \
  --confluence-space YOUR_SPACE_KEY \
  --confluence-page "Your API Spec Page Title" \
  --keyword appointment
```

**What the output looks like:**

> The step 5 log line still says "Copilot generation + Gemini evaluation loop" — that's a stale
> label from an earlier version of the code. The actual provider is Groq throughout.

```
[1/6] Fetching Jira ticket YOUR-TICKET-KEY...
  Summary : Implement GET endpoint for appointments
  Status  : In Progress

[2/6] Fetching Confluence page 'Your API Spec Page Title'...
  Page : Your API Spec Page Title
  URL  : https://your-org.atlassian.net/wiki/spaces/...

[3/6] Resolving target repos...
  Detected HTTP method: GET
  Service keyword: 'appointment'
  Target repos (2):
    - your-org/Appointment-Service  [api]
    - your-org/Appointment-DB-Service  [database]

[4/6] Building prompt.md...
  Saved prompt.md (using GET.md template)

[5/6] Running Copilot generation + Gemini evaluation loop...
[!] Generator model: llama-3.3-70b-versatile
[!] Judge model:     llama-3.3-70b-versatile

--- Iteration 1 / 3 ---
[!] Generating code with llama-3.3-70b-versatile...
[+] Saved response to 'resp1.txt'
[+] Written files: ['routes/appointment_routes.py', 'services/booking_service.py']
[!] Judging with llama-3.3-70b-versatile...
[+] Saved judge response to 'judge1.txt'

[+] Judge approved the code!
  Saved generated_solution.md locally

[6/6] Opening PRs in parallel across 2 repo(s)...
  [api] Deploying to your-org/Appointment-Service...
    [api] Committed prompt.md
    [api] Committed generated_solution.md
    [api] Committed app/routes/appointment_routes.py
  [api] PR opened: https://github.com/your-org/Appointment-Service/pull/12
  [database] Deploying to your-org/Appointment-DB-Service...
  [database] PR opened: https://github.com/your-org/Appointment-DB-Service/pull/8

============================================
[+] Pipeline complete! 2 PR(s) opened:
    [api] your-org/Appointment-Service → https://github.com/your-org/Appointment-Service/pull/12
    [database] your-org/Appointment-DB-Service → https://github.com/your-org/Appointment-DB-Service/pull/8
============================================

[+] Adding comment to Jira ticket YOUR-TICKET-KEY...
[+] Comment added to YOUR-TICKET-KEY.
```

### Test the LLM loop only (no Jira, no GitHub)

If `prompt.md` already exists in `orchestrator/`, you can test the generation loop in isolation:

```bash
cd orchestrator
python orchestrator.py
```

Output: `generated_solution.md` and updated files in `app/`. Useful for tuning prompts without touching Jira or GitHub.

---

## Webhook Mode

The webhook server listens for Jira issue events and triggers the pipeline automatically whenever a matching ticket is assigned.

### 1. Start the webhook server

```bash
cd orchestrator
uvicorn webhook_server:app --host 0.0.0.0 --port 8000
```

Confirm it is running:

```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

> The webhook server reads `CONFLUENCE_SPACE`, `CONFLUENCE_PAGE`, `BASE_BRANCH`, and
> `COPILOT_ASSIGNEE` from `orchestrator/.env`. Make sure these are set before starting it.

**Keeping the server running past your terminal session:**

For a persistent deployment, run it as a background service rather than a foreground process.

- **Linux (systemd):** Create a unit file at `/etc/systemd/system/pipeline-webhook.service`, then `systemctl enable --now pipeline-webhook`
- **macOS:** Use a `launchd` plist, or run `nohup uvicorn webhook_server:app --host 0.0.0.0 --port 8000 &`
- **Any platform (Docker):** Build a container from the `orchestrator/` directory and run it with your chosen container host

ngrok is for local development only. For a stable production URL, deploy the server to any cloud VM or container service (Railway, Fly.io, EC2, etc.) and register that fixed URL in Jira instead.

### 2. Expose it with ngrok

In a separate terminal:

```bash
ngrok http 8000
```

Copy the HTTPS URL — something like `https://abcd-1234.ngrok-free.app`.

> **Free ngrok URLs change every time you restart ngrok.** Update the Jira webhook URL
> whenever you get a new one. Consider a paid ngrok plan or a fixed deployment if you want
> a stable URL.

### 3. Register the webhook in Jira

1. Go to **Jira Settings → System → Webhooks**
2. Click **Create a WebHook**
3. Set the URL to `https://your-ngrok-url.ngrok-free.app/webhook`
4. Under **Events**, check **Issue → updated**
5. Save

### 4. Trigger a run

Assign a Jira ticket to the user set in `COPILOT_ASSIGNEE` (or any user if that setting is empty). The ticket summary or description must contain a keyword from `service_groups.json`.

The terminal running the webhook server will show the full pipeline progress.

**Webhook responses:**

| Response | Meaning |
|---|---|
| `{"status": "accepted", "ticket": "...", "keyword": "...", "target_repos": [...]}` | Pipeline triggered in background |
| `{"status": "ignored", "reason": "no assignee set"}` | Ticket has no assignee |
| `{"status": "ignored", "reason": "assignee 'name' is not the copilot agent"}` | Assignee does not match `COPILOT_ASSIGNEE` — the actual assignee display name is included in the message |
| `{"status": "ignored", "reason": "no matching service keyword found", "available_keywords": [...]}` | No keyword from `service_groups.json` found in ticket text — the list of valid keywords is returned |

---

## Understanding the Output

After a successful pipeline run, several files are saved locally in `orchestrator/`:

| File | Contents |
|---|---|
| `prompt.md` | The complete prompt that was sent to the LLM — template + Jira ticket + Confluence spec |
| `generated_solution.md` | The raw LLM output from the final approved iteration |
| `resp1.txt`, `resp2.txt`, ... | Raw model response from each generation iteration |
| `judge1.txt`, `judge2.txt`, ... | Raw judge response from each evaluation iteration |

The `resp*.txt` and `judge*.txt` files are intermediate debug artifacts. They are covered by `orchestrator/.gitignore` and will not be committed. `prompt.md` and `generated_solution.md` are also gitignored locally but **are** committed to the feature branch in each matched GitHub repo.

The `app/` directory is updated with whatever code the LLM generated. These files are also committed to the feature branch.

**The judge loop:**

The LLM generates code, then the same model evaluates it against the original requirements and returns `{"met_conditions": true/false, "feedback": "..."}`. If it fails, the feedback is injected back as additional requirements and the model tries again — up to 3 times.

> **If the judge rejects all 3 iterations**, the pipeline commits the last generated output
> anyway and still opens the PR. Always review generated PRs before merging. The judge is a
> quality filter, not a guarantee.

**Feature branch naming:**

```
feature/{ticket-key}-{method}-{timestamp}
# example: feature/kan-22-patch-20240515143022
```

---

## Deploying for Your Organization

This section covers everything an admin needs to do **once** to get the pipeline running for their whole team, followed by two production deployment options (systemd and Docker).

---

### One-Time Setup Checklist

Work through these steps in order. Each step only needs to be done once per organization.

---

#### 1. Create a dedicated Jira bot account

Create a **separate Atlassian account** for the pipeline — not a personal developer account. This is the account Jira tickets get assigned to in order to trigger the pipeline automatically.

Suggested email: `pipeline-bot@yourcompany.com`

Once the account exists:
- Log into it and generate an API token at [id.atlassian.net/manage-profile/security/api-tokens](https://id.atlassian.net/manage-profile/security/api-tokens)
- In your Jira project, grant this account **Developer** or **Member** role so it can receive assignments and post comments
- Set `COPILOT_ASSIGNEE=pipeline-bot@yourcompany.com` in `orchestrator/.env`

> Using a dedicated account means every developer can trigger the pipeline just by reassigning
> a ticket, and all pipeline-generated comments in Jira come from one identifiable bot account
> rather than a developer's personal account.

---

#### 2. Generate all credentials

Using the bot account, collect the following and fill them into `orchestrator/.env`:

| Credential | Where to generate | `.env` variable |
|---|---|---|
| Jira API token | Atlassian account security settings | `JIRA_API_TOKEN` |
| Confluence API token | Same token works | `CONFLUENCE_API_TOKEN` |
| GitHub PAT (`repo` scope) | [github.com/settings/tokens](https://github.com/settings/tokens) | `GITHUB_TOKEN` |
| Groq API key | [console.groq.com](https://console.groq.com) | `GROQ_API_KEY` |

Make sure the GitHub token has **push access to every repo** listed in `service_groups.json`. If your repos are under a GitHub organization, the token owner must be a member of that org.

---

#### 3. Configure your services

Edit `orchestrator/service_groups.json` to map your service names to your GitHub repos. Full instructions are in the [Configure for Your Repos](#configure-for-your-repos) section.

Each keyword must be a word that naturally appears in your Jira ticket text. When a developer writes a ticket like *"Implement DELETE endpoint for appointments"*, the pipeline picks up `appointment` automatically.

---

#### 4. Set up your prompt templates

Create a `prompts/` directory in a GitHub repo your team owns, and add one `.md` file per HTTP method (`GET.md`, `POST.md`, `PUT.md`, `PATCH.md`, `DELETE.md`). Set `PROMPTS_REPO=your-org/your-repo` in `.env`.

Full instructions are in the [Set Up Prompt Templates](#set-up-prompt-templates) section.

> This is the most important step for code quality. Templates that describe your exact file
> structure, naming conventions, and validation patterns produce PRs that need minimal edits.

---

#### 5. Deploy the webhook server

See [Production Deployment](#production-deployment) below. Your server needs a **public HTTPS URL** — Jira Cloud only fires webhooks to HTTPS endpoints.

---

#### 6. Register the webhook in Jira

Once your server is running and reachable over HTTPS:

1. Go to **Jira Settings → System → Webhooks**
2. Click **Create a WebHook**
3. Set the URL to `https://your-domain.com/webhook`
4. Under **Events**, check **Issue → updated**
5. Leave all other event types unchecked
6. Save

From this point forward, whenever any ticket in your project is assigned to the bot account, Jira fires an event to your server and the pipeline runs automatically.

---

#### How your team uses it day-to-day

Once the above is set up, a developer's workflow is:

1. **Write a Jira ticket** describing the endpoint — make sure the service name appears in the summary or description (e.g. *"Implement PATCH /appointments/{id}/status"*)
2. **Assign the ticket** to the bot account (`pipeline-bot@yourcompany.com`)
3. **Wait ~1–2 minutes** — the pipeline fetches the ticket, generates code, and opens PR(s)
4. **Review the PR** in GitHub — check the generated code, run your tests, merge or adjust as needed
5. **Check the Jira ticket** — the bot posts all PR links as a comment so the ticket stays the single source of truth

No command line needed for developers. The whole flow is Jira → GitHub.

---

### Production Deployment

The webhook server needs to run persistently on a machine with a stable public HTTPS URL. Two options are given below — systemd for a plain Linux server, and Docker for teams that prefer containers.

---

#### Option A — Linux server with systemd and nginx

**What you need:**
- A Linux VM (Ubuntu 22.04 recommended) with a public IP and ports 80 and 443 open in your cloud firewall / security group
- A domain or subdomain pointing to that IP (e.g. `pipeline.yourcompany.com`)
- Python 3.10+, nginx, and certbot installed

> **Node.js is not needed on the server.** The MCP servers (`jira-mcp-server/`, `confluence-mcp-server/`, `github-mcp-server/`) are only used with Claude Desktop on developer machines — they play no part in the automated webhook pipeline.

**Step 1 — Clone and install on the server**

```bash
git clone https://github.com/your-org/your-fork.git /opt/pipeline
cd /opt/pipeline/orchestrator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Step 1b — Create a dedicated system user**

The service should not run as `root` or `www-data`. Create a minimal user that owns only the pipeline directory:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin pipeline
sudo chown -R pipeline:pipeline /opt/pipeline
```

**Step 2 — Create your `.env`**

```bash
cp /opt/pipeline/orchestrator/.env.example /opt/pipeline/orchestrator/.env
# fill in all values
nano /opt/pipeline/orchestrator/.env
```

**Step 3 — Create the systemd service**

Create `/etc/systemd/system/pipeline-webhook.service`:

```ini
[Unit]
Description=AI Pipeline Webhook Server
After=network.target

[Service]
Type=simple
User=pipeline
WorkingDirectory=/opt/pipeline/orchestrator
EnvironmentFile=/opt/pipeline/orchestrator/.env
ExecStart=/opt/pipeline/orchestrator/venv/bin/uvicorn webhook_server:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pipeline-webhook
sudo systemctl start pipeline-webhook

# confirm it is running
sudo systemctl status pipeline-webhook
curl http://127.0.0.1:8000/health
# → {"status": "ok"}
```

**Step 4 — Set up nginx and TLS**

Install certbot and get a certificate:

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo certbot --nginx -d pipeline.yourcompany.com
```

Create `/etc/nginx/sites-available/pipeline`:

```nginx
server {
    listen 443 ssl;
    server_name pipeline.yourcompany.com;

    ssl_certificate     /etc/letsencrypt/live/pipeline.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pipeline.yourcompany.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}

server {
    listen 80;
    server_name pipeline.yourcompany.com;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/pipeline /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Your webhook server is now live at `https://pipeline.yourcompany.com/webhook`.

> The `/webhook` endpoint returns an immediate `{"status": "accepted"}` response — the actual
> pipeline work runs in the background. The 60s timeout is the nginx default and is more than
> sufficient. No special timeout value is needed.

---

#### Option B — Docker

**Step 1 — Create a `.dockerignore` inside `orchestrator/`**

```
.env
__pycache__/
*.pyc
.venv/
venv/
resp*.txt
judge*.txt
generated_solution.md
prompt.md
```

This keeps credentials and build artifacts out of the image.

**Step 2 — Create a `Dockerfile` inside `orchestrator/`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "webhook_server:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3 — Create `docker-compose.yml` at the repo root**

```yaml
services:
  pipeline:
    build: ./orchestrator
    ports:
      - "8000:8000"
    env_file:
      - ./orchestrator/.env
    restart: unless-stopped
```

**Step 4 — Build and start**

```bash
docker compose up -d

# confirm it is running
docker compose logs -f pipeline
curl http://localhost:8000/health
# → {"status": "ok"}
```

**Step 5 — TLS**

Docker exposes the server on port 8000 over plain HTTP. Put a TLS-terminating reverse proxy in front of it before registering the URL with Jira.

The simplest option is **Caddy** — it handles TLS certificates automatically:

```
# Caddyfile
pipeline.yourcompany.com {
    reverse_proxy localhost:8000
}
```

```bash
caddy run --config Caddyfile
```

Caddy fetches and renews a Let's Encrypt certificate automatically. No certbot, no nginx config needed.

---

#### Verifying the deployment

After either option, confirm the full path works end-to-end before registering in Jira:

```bash
# health check over HTTPS
curl https://pipeline.yourcompany.com/health
# → {"status": "ok"}

# simulate a Jira webhook payload
curl -X POST https://pipeline.yourcompany.com/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "issue": {
      "key": "TEST-1",
      "fields": {
        "summary": "Test appointment endpoint",
        "description": "",
        "assignee": {
          "emailAddress": "pipeline-bot@yourcompany.com",
          "displayName": "Pipeline Bot"
        }
      }
    }
  }'
# → {"status": "accepted", ...}  or  {"status": "ignored", "reason": "..."}
```

Once the health check passes and the test payload returns a sensible response, register `https://pipeline.yourcompany.com/webhook` in Jira and you are done.

---

## Claude Desktop — Optional

You can register the MCP servers with Claude Desktop to interact with Jira, Confluence, and GitHub manually through conversation. This is completely separate from the automated pipeline — the MCP servers share no code with `pipeline.py` or `webhook_server.py`. Use this mode for testing integrations, doing one-off queries, or exploring ticket/repo state interactively.

### 1. Create `.env` files for each MCP server

Each server needs its own credentials file. These files are **not** covered by `orchestrator/.gitignore` — add them to a root-level `.gitignore` or do not commit them.

**`jira-mcp-server/.env`**
```
JIRA_DOMAIN=https://your-org.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_jira_api_token
```

**`confluence-mcp-server/.env`**
```
CONFLUENCE_DOMAIN=https://your-org.atlassian.net
CONFLUENCE_EMAIL=you@company.com
CONFLUENCE_API_TOKEN=your_confluence_api_token
```

**`github-mcp-server/.env`**
```
GITHUB_TOKEN=ghp_your_token
GITHUB_OWNER=your-github-username-or-org
```

### 2. Register the servers in Claude Desktop

Config file locations:
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Replace the paths with the absolute path to your clone:

**macOS / Linux:**
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

**Windows:**
```json
{
  "mcpServers": {
    "jira": {
      "command": "node",
      "args": ["C:\\Users\\YourName\\path\\to\\MCP\\jira-mcp-server\\server.js"]
    },
    "confluence": {
      "command": "node",
      "args": ["C:\\Users\\YourName\\path\\to\\MCP\\confluence-mcp-server\\server.js"]
    },
    "github": {
      "command": "node",
      "args": ["C:\\Users\\YourName\\path\\to\\MCP\\github-mcp-server\\server.js"]
    }
  }
}
```

Restart Claude Desktop after saving the config.

### 3. Available tools

| Server | Tool | What it does |
|---|---|---|
| jira | `get_jira_issue` | Fetch a Jira issue by key |
| jira | `add_jira_comment` | Post a comment on a Jira issue |
| jira | `ping` | Health check — returns `{"status": "pong", "timestamp": "..."}` |
| confluence | `get_confluence_page` | Fetch a Confluence page by space key and title |
| confluence | `ping` | Health check — returns `{"status": "pong", "timestamp": "..."}` |
| github | `get_repo_file` | Read a file from a GitHub repo |
| github | `update_file` | Create or update a file on a branch |
| github | `create_branch` | Create a new branch from a base branch |
| github | `create_pr` | Open a pull request |

> **GitHub MCP tool — `repo` parameter:** The GitHub MCP server prepends `GITHUB_OWNER` to the
> repo name automatically. Pass **only the repo name** (e.g. `Appointment-Service`), not the full
> `owner/repo` format. Example: ask Claude *"get the README from Appointment-Service"* — the server
> constructs `GITHUB_OWNER/Appointment-Service` internally.

---

## Troubleshooting

**`ignored: no assignee set`**
The ticket has no assignee. Assign it before the webhook fires.

**`ignored: assignee is not the copilot agent`**
The assignee email does not match `COPILOT_ASSIGNEE` in `.env`. Either update the env var or assign the ticket to the configured user.

**`ignored: no matching service keyword found`**
No keyword from `service_groups.json` appears in the ticket text. Check `service_groups.json` keys against the actual ticket wording, or pass `--keyword your-keyword` manually when running from CLI.

**`404` on Confluence fetch**
The space key or page title does not match. Both are case-sensitive. Find the space key in the Confluence URL: `.../wiki/spaces/SPACEKEY/...`. For personal spaces, copy the full `~xxxxxxxx` string from the URL — do not guess it.

**`401` on Jira or Confluence**
Your API token is invalid or expired. Regenerate it at `id.atlassian.net/manage-profile/security/api-tokens`.

**`403` or `404` on GitHub**
Regenerate your token at `github.com/settings/tokens` and confirm it has `repo` scope. Also check that the `repo` values in `service_groups.json` use the exact `owner/repo-name` format as it appears in the GitHub URL — the pipeline resolves the owner from that string, not from any env var.

**Groq rate limit errors**
The free tier has per-minute token limits. If a run fails with a 429 error, wait a minute and retry. For teams running many tickets, consider upgrading to a paid Groq plan or switching to a different provider (requires editing two lines in `orchestrator.py` — see the AI Model note in the Credentials section).

**Generated code is too generic / doesn't match your codebase**
The prompt templates in your `PROMPTS_REPO` are the most important lever here. Add details about your specific file layout, import patterns, base classes, and naming conventions. The more precisely your templates describe your architecture, the more accurate the output.

**`python webhook_server.py` does nothing**
The server must be started with uvicorn, not run directly with Python:
```bash
uvicorn webhook_server:app --host 0.0.0.0 --port 8000
```

**ngrok URL expired**
Free ngrok URLs change on each restart. Update the Jira webhook URL under **Jira Settings → System → Webhooks** after every ngrok restart.

**Generated PR opens but code calls `localhost:8001`**
The generated `app/` code proxies all data operations to a downstream database service. This is specific to the example architecture the prompts were designed around. If your repos connect directly to a database, update your prompt templates to reflect your actual connection pattern.
