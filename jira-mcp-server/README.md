# jira-mcp-server

A minimal Model Context Protocol (MCP) server that exposes Jira issue lookup functionality.

## Available tools

- `get_jira_issue` - Fetch Jira issue by key (requires `issueKey` argument).
- `ping` - Health-check tool; returns `{ "status": "pong", "timestamp": "..." }`.

## Running the server

1. Install dependencies:
   ```sh
   npm install
   ```

2. Create a `.env` file with Jira credentials:
   ```text
   JIRA_DOMAIN=https://your-domain.atlassian.net
   JIRA_EMAIL=you@example.com
   JIRA_API_TOKEN=your_api_token
   ```

3. Start the MCP server (it writes to stdout/stdin):
   ```sh
   node server.js
   ```

## Testing

You can test the server by invoking the `ping` tool from a client to ensure the MCP server is responding:

```js
// pseudocode
const response = await client.callTool({ name: 'ping', arguments: {} });
console.log(response);
```