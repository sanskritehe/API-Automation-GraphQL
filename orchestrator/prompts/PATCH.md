# Copilot Agent – PATCH Endpoint Implementation

You are an AI coding agent. Your task is to implement a PATCH (partial update) REST API endpoint.

These instructions are generic and apply to ANY repository and ANY resource.

---

## Step 1 – Read the Jira Ticket

Use the Jira tool to fetch the ticket provided.

Extract:
- The resource name (e.g. "appointment", "user", "order")
- The field being patched (e.g. "status", "time", "priority")
- The endpoint to implement (e.g. PATCH /appointments/{id}/status)
- Any state transition rules or validation logic called out
- The Confluence page reference for the API spec

---

## Step 2 – Fetch API Specification from Confluence

Use the Confluence tool to fetch the page referenced in the Jira ticket.

Find the section for the PATCH endpoint of the resource.

Extract:
- The exact endpoint path and path parameters
- The exact request body format
- The exact response JSON format on success
- The error response format (especially 404 and 400)
- Any allowed values or transition rules for the patched field

---

## Step 3 – Read Existing Code

Use the GitHub tool to read the existing implementation files in the repository.

Understand:
- How existing endpoints are structured
- How records are queried and updated
- What Pydantic models already exist
- What imports are already present
- Whether this is an API gateway service (calls another service) or a database service (writes directly)

DO NOT modify any already implemented endpoints.

---

## Step 4 – Implement the PATCH Endpoint

A PATCH endpoint must:
- Accept the resource ID as a path parameter
- Accept a request body with only the field(s) being patched
- Query the resource by ID and return 404 if not found
- If state transition rules apply: validate the transition is allowed, return 400 with a clear message if not
- Apply the patch (update only the specified field, leave all others unchanged)
- Return the full updated resource object on success
- Follow the exact same code style as existing endpoints
- Use dependency injection for sessions or clients
- Ensure all necessary imports exist (e.g. HTTPException)

---

## Step 5 – Create a Branch

Use the GitHub tool to create a new branch:
- Branch name: feature/{jira-ticket-id}-patch-{resource-name}
- Base branch: main

---

## Step 6 – Push the Code

Push only the minimal necessary changes to the feature branch.

Commit message format:
"[{jira-ticket-id}] Implement PATCH /{resource}/{id}/{field} endpoint"

---

## Step 7 – Raise a Pull Request

Create a PR with:
- Title: [{jira-ticket-id}] Implement PATCH /{resource}/{id}/{field}
- Body: what was implemented, files changed, state transition rules if any, Jira and Confluence references
- Head: feature branch
- Base: main

---

## Rules

- Never modify already working endpoints
- Always return 404 if resource not found
- Always return 400 with a clear message if a state transition is invalid
- Always return the full updated resource on success
- Always follow existing code style
- Always follow the Confluence spec for request and response format
- Minimal changes only — do not refactor unrelated code
