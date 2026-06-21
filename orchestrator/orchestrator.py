"""
Code generation + judge loop (Groq LLaMA).

Supports role-specific prompts for the 4-repo GraphQL architecture:
  api       — Appointment-Service subgraph (Strawberry Federation)
  database  — Appointment-Database-Service subgraph (SQLAlchemy + Strawberry)
  gateway   — REST API Gateway (REST → GraphQL via run_query)
  datagraph — Apollo Router config (YAML only, no Python)
  <none>    — Generic FastAPI REST service (legacy behaviour)

Standalone usage:
    python orchestrator.py                     # reads prompt.md from CWD

Imported usage:
    from orchestrator import run_orchestrator
    final_code = await run_orchestrator(prompt_content, role="gateway", existing_code="...")
"""

import asyncio
import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(override=True)

GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "llama-3.3-70b-versatile")
JUDGE_MODEL     = os.getenv("JUDGE_MODEL",     "llama-3.3-70b-versatile")

# ---------------------------------------------------------------------------
# Role-specific system prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPTS = {
    "api": (
        "You are an expert FastAPI + Strawberry GraphQL developer working on an Apollo Federation subgraph. "
        "The service exposes BOTH a REST API (app/routes/) AND a GraphQL subgraph endpoint (/graphql). "
        "The subgraph schema lives in graphql_schema.py at the repo root. "
        "It uses strawberry.federation.Schema with types decorated @strawberry.federation.type(keys=['id']). "
        "Resolvers call the existing service functions in app/services/. "
        "For a new feature you must: "
        "1) Add any new input/output types to graphql_schema.py. "
        "2) Add the mutation or query resolver to the Query/Mutation class in graphql_schema.py. "
        "3) Wire the resolver to the matching app/services/ function. "
        "Output ONLY files that need to change — graphql_schema.py is the primary target. "
        "Do NOT change REST routes, models, services, or db_client unless the requirement explicitly asks. "
        "CRITICAL: FastAPI router paths are RELATIVE to the router prefix. "
        "Never repeat the resource name inside the decorator (no '/appointments' inside a router with prefix='/appointments'). "
        "Format every changed file as:\n"
        "### FILE: <path>\n```python\n<full file content>\n```"
    ),
    "database": (
        "You are an expert FastAPI + SQLAlchemy + Strawberry GraphQL developer working on the database layer subgraph. "
        "The service stores records in SQLite via SQLAlchemy and exposes them through BOTH REST endpoints (app/main.py) "
        "AND a GraphQL subgraph endpoint at /graphql. "
        "The subgraph schema lives in graphql_schema.py at the repo root. "
        "It uses strawberry.federation.Schema and reads/writes via SQLAlchemy SessionLocal. "
        "For a new feature you must: "
        "1) Add any new SQLAlchemy model fields to app/models.py if needed. "
        "2) Add the mutation or query to graphql_schema.py — resolvers open a SessionLocal and commit directly. "
        "Output ONLY files that need to change (graphql_schema.py and/or app/models.py). "
        "Do NOT change REST endpoints, db engine setup, or unrelated logic. "
        "Format every changed file as:\n"
        "### FILE: <path>\n```python\n<full file content>\n```"
    ),
    "gateway": (
        "You are an expert FastAPI developer working on a REST API Gateway. "
        "This service ONLY exposes REST endpoints externally — it does NOT talk to the database directly. "
        "All data access goes through the GraphQL datagraph via httpx: "
        "  from app.graphql_client import run_query  # run_query(gql_string, variables_dict) -> data dict\n"
        "The DATAGRAPH_URL env var points to the federation router (default http://localhost:4000). "
        "For a new feature you must add a REST route in app/routes/appointments.py that: "
        "1) Accepts the REST request (path/body/query params). "
        "2) Calls run_query() with the appropriate GraphQL mutation or query string and variables. "
        "3) Returns the relevant portion of the GraphQL response. "
        "Do NOT add a /graphql endpoint. Do NOT call appointment services directly. "
        "CRITICAL: Route paths are RELATIVE to router prefix='/appointments'. "
        "Use '/' for the collection, '/{id}' for a single item. "
        "Format every changed file as:\n"
        "### FILE: <path>\n```python\n<full file content>\n```"
    ),
    "datagraph": (
        "You are working on the Apollo Router federation layer (graphql-datagraph). "
        "This repo contains configuration files and a compose script. "
        "Files: router.yaml (Apollo Router config), supergraph.yaml (federation composition config listing subgraph URLs), "
        "compose.sh (shell script that runs rover supergraph compose to regenerate supergraph.graphql). "
        "The supergraph.graphql is auto-generated by 'rover supergraph compose' and must NOT be edited manually. "
        "For every pipeline run you MUST output an updated compose.sh that runs: "
        "  rover supergraph compose --config supergraph.yaml > supergraph.graphql "
        "This command introspects each subgraph listed in supergraph.yaml, picks up their latest schema changes, "
        "and regenerates the unified supergraph.graphql used by Apollo Router. "
        "The compose.sh must also restart the router after composing so it picks up the new supergraph. "
        "Additionally: "
        "- If a new subgraph service is being added, add it to supergraph.yaml. "
        "- If the router config needs updating (CORS, ports), update router.yaml. "
        "Always output compose.sh. For other files, only output them if they need to change. "
        "Format every file as:\n"
        "### FILE: <filename>\n```bash\n<full file content>\n```\n"
        "or for yaml files:\n"
        "### FILE: <filename>\n```yaml\n<full file content>\n```"
    ),
}

_GENERIC_SYSTEM_PROMPT = (
    "You are an expert FastAPI developer working on a layered microservice. "
    "The service has three layers: routes → services → db_client. "
    "You will receive requirements and the full existing codebase. "
    "Output ONLY the files that need to be created or modified. "
    "Format every file exactly like this — no exceptions:\n\n"
    "### FILE: <relative/path/to/file.py>\n"
    "```python\n<complete file content>\n```\n\n"
    "Rules:\n"
    "- Output the COMPLETE content of each file, not just the new lines.\n"
    "- Never modify files that are unrelated to the requirement.\n"
    "- No explanation, no commentary outside the FILE blocks.\n"
    "- Do not perform any git operations.\n"
    "- CRITICAL: FastAPI routers use a prefix (e.g. APIRouter(prefix='/appointments')). "
    "Route paths inside the router are RELATIVE to that prefix. "
    "NEVER repeat the resource name in the route path decorator — "
    "use '/' for the collection endpoint, '/{id}' for item endpoints, "
    "and short sub-paths like '/book' only for distinct actions. "
    "Doubling the prefix (e.g. @router.post('/appointments') inside a router "
    "that already has prefix='/appointments') creates a broken '/appointments/appointments' path."
)

# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _read_app_files(app_dir: str) -> str:
    """Read all Python files in app_dir and return as formatted context."""
    blocks = []
    for root, _, files in os.walk(app_dir):
        for filename in sorted(files):
            if not filename.endswith(".py") or "__pycache__" in root:
                continue
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, app_dir).replace("\\", "/")
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            blocks.append(f"### FILE: {rel_path}\n```python\n{content}\n```")
    return "\n\n".join(blocks)


def _parse_and_write_files(response_text: str, app_dir: str) -> list[str]:
    """Parse ### FILE: blocks from response and write them to app_dir."""
    pattern = r"###\s*FILE:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```"
    matches = re.findall(pattern, response_text, re.DOTALL)
    written = []
    for rel_path, code in matches:
        rel_path = rel_path.strip()
        abs_path = os.path.join(app_dir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(code)
        written.append(rel_path)
    return written


def parse_generated_files(response_text: str) -> dict[str, str]:
    """
    Parse ### FILE: blocks from response and return {path: content} dict.
    Used when writing to GitHub rather than local disk.
    """
    pattern = r"###\s*FILE:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```"
    matches = re.findall(pattern, response_text, re.DOTALL)
    return {m[0].strip(): m[1] for m in matches}

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_orchestrator(
    prompt_content: str,
    *,
    role: str = "",
    existing_code: str = "",
    app_dir: str = None,
) -> str:
    """
    Run the code generation + judge loop.

    Args:
        prompt_content:  Requirements / spec text (Jira + Confluence context).
        role:            Repo role — "api", "database", "gateway", "datagraph", or "" for legacy.
        existing_code:   Pre-fetched repo code string (### FILE: blocks).
                         If empty and app_dir is set, reads from app_dir instead.
        app_dir:         Local directory to read/write files (legacy path). Ignored when
                         existing_code is provided.

    Returns:
        The final generated code string (approved or best-effort after max retries).
    """
    system_prompt = _SYSTEM_PROMPTS.get(role, _GENERIC_SYSTEM_PROMPT)

    # Determine existing code context
    if existing_code:
        code_context = existing_code
    elif app_dir:
        app_dir = os.path.abspath(app_dir)
        code_context = _read_app_files(app_dir)
    else:
        app_dir = os.path.join(os.path.dirname(__file__), "app")
        app_dir = os.path.abspath(app_dir)
        code_context = _read_app_files(app_dir)

    client = AsyncOpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )
    max_retries = 2
    final_code = ""
    current_requirements = prompt_content

    print(f"  [gen] role={role or 'generic'}  model={GENERATOR_MODEL}")

    async def _llm_call(messages: list, model: str) -> str:
        """Call the LLM with retry on Groq rate limits. Waits 65s (full TPM window) on each hit."""
        for attempt in range(4):
            try:
                resp = await client.chat.completions.create(model=model, messages=messages)
                return resp.choices[0].message.content or ""
            except Exception as e:
                err = str(e)
                if "rate_limit" in err.lower() or "429" in err:
                    # Try to parse Groq's exact "try again in X.Xs" hint, fall back to 65s
                    m = re.search(r"try again in ([\d.]+)s", err)
                    wait = float(m.group(1)) + 5 if m else 65
                    print(f"  [llm] Rate limit — waiting {wait:.0f}s (attempt {attempt+1}/4)...")
                    await asyncio.sleep(wait)
                else:
                    raise
        raise RuntimeError("LLM rate limit exceeded after 4 retries")

    for iteration in range(1, max_retries + 1):
        print(f"  --- Iteration {iteration}/{max_retries} ---")

        # 1. GENERATION
        user_message = (
            f"## Requirements\n\n{current_requirements}\n\n"
            f"## Existing Codebase\n\n{code_context}"
        )

        generated_code = await _llm_call(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
            GENERATOR_MODEL,
        )

        with open(f"resp{iteration}_{role or 'generic'}.txt", "w", encoding="utf-8") as f:
            f.write(generated_code)

        if not generated_code.strip() or "NO_CHANGES_NEEDED" in generated_code:
            print(f"  [gen] No changes needed for role={role or 'generic'}")
            final_code = generated_code
            break

        # Write to local app_dir for legacy path
        if app_dir and not existing_code:
            written = _parse_and_write_files(generated_code, app_dir)
            print(f"  [gen] Written: {written}")

        # 2. EVALUATION
        judge_prompt = (
            "You are a rigorous code evaluator.\n"
            "Compare the Generated Code against the Original Requirements.\n"
            "Output strictly valid JSON with exactly two keys:\n"
            '- "met_conditions": boolean (true only if ALL requirements are fully met)\n'
            '- "feedback": string (specific actionable issues if false, empty string if true)\n'
            "No markdown fences. No text outside the JSON object.\n\n"
            f"Original Requirements:\n{prompt_content}\n\n"
            f"Generated Code:\n{generated_code}"
        )

        response_text = await _llm_call(
            [{"role": "user", "content": judge_prompt}],
            JUDGE_MODEL,
        )

        with open(f"judge{iteration}_{role or 'generic'}.txt", "w", encoding="utf-8") as f:
            f.write(response_text)

        try:
            raw = response_text.strip().strip("`").removeprefix("json").strip()
            evaluation = json.loads(raw)
        except Exception as e:
            print(f"  [judge] Parse failed ({e}), forcing retry.")
            evaluation = {"met_conditions": False, "feedback": "Parse error — regenerate cleanly."}

        if evaluation.get("met_conditions"):
            print(f"  [judge] Approved on iteration {iteration}.")
            final_code = generated_code
            break
        else:
            feedback = evaluation.get("feedback", "")
            print(f"  [judge] Rejected: {feedback[:120]}")
            current_requirements = (
                f"The previous code failed review.\n\nFeedback:\n{feedback}\n\n"
                f"Original requirements:\n{prompt_content}\n\n"
                f"Fix only the issues listed. Output the corrected files in full."
            )
            if iteration == max_retries:
                print(f"  [judge] Max retries — using last generated code.")
                final_code = generated_code

    return final_code


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

async def _standalone():
    prompt_file = "prompt.md"
    if not os.path.exists(prompt_file):
        raise FileNotFoundError(f"'{prompt_file}' not found. Run pipeline.py or create it manually.")

    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_content = f.read()

    final_code = await run_orchestrator(prompt_content)

    with open("generated_solution.md", "w", encoding="utf-8") as f:
        f.write(final_code)

    print("\n[+] Finished! Final code saved to 'generated_solution.md'")


if __name__ == "__main__":
    asyncio.run(_standalone())
