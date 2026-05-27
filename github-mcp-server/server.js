import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ListToolsRequestSchema, CallToolRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import axios from "axios";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, ".env") });

const server = new Server(
  {
    name: "github-mcp-server",
    version: "1.0.0"
  },
  {
    capabilities: { tools: {} }
  }
);

const github = axios.create({
  baseURL: "https://api.github.com",
  headers: {
    Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
    Accept: "application/vnd.github+json"
  }
});

/*
List all tools exposed by this MCP server
*/
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "get_repo_file",
      description: "Fetch a file from a GitHub repository",
      inputSchema: {
        type: "object",
        properties: {
          repo: { type: "string" },
          path: { type: "string" }
        },
        required: ["repo", "path"]
      }
    },
    {
      name: "update_file",
      description: "Create or update a file in a GitHub repository",
      inputSchema: {
        type: "object",
        properties: {
          repo: { type: "string" },
          path: { type: "string" },
          content: { type: "string" },
          message: { type: "string" },
          branch: { type: "string" }
        },
        required: ["repo", "path", "content", "message", "branch"]
      }
    },
    {
      name: "create_branch",
      description: "Create a new branch in a GitHub repository from base branch",
      inputSchema: {
        type: "object",
        properties: {
          repo: { type: "string" },
          branch: { type: "string" },
          base: { type: "string" }
        },
        required: ["repo", "branch", "base"]
      }
    },
    {
      name: "create_pr",
      description: "Create a Pull Request in a GitHub repository",
      inputSchema: {
        type: "object",
        properties: {
          repo: { type: "string" },
          title: { type: "string" },
          body: { type: "string" },
          head: { type: "string" },
          base: { type: "string" }
        },
        required: ["repo", "title", "head", "base"]
      }
    }
  ]
}));

/*
Tool execution
*/
server.setRequestHandler(CallToolRequestSchema, async (request) => {

  const owner = process.env.GITHUB_OWNER;

  /*
  TOOL: get_repo_file
  */
  if (request.params.name === "get_repo_file") {

    const { repo, path } = request.params.arguments;

    const res = await github.get(
      `/repos/${owner}/${repo}/contents/${path}`
    );

    const content = Buffer.from(res.data.content, "base64").toString();

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ path, content }, null, 2)
        }
      ]
    };
  }

  /*
  TOOL: update_file
  Now accepts a branch parameter so files are written to the feature branch
  */
  if (request.params.name === "update_file") {

    const { repo, path, content, message, branch } = request.params.arguments;

    let sha = null;

    // Check if file already exists on this branch
    try {
      const file = await github.get(
        `/repos/${owner}/${repo}/contents/${path}`,
        { params: { ref: branch } }
      );
      sha = file.data.sha;
    } catch (err) {
      // File doesn't exist yet — that's fine
    }

    const encodedContent = Buffer.from(content).toString("base64");

    const res = await github.put(
      `/repos/${owner}/${repo}/contents/${path}`,
      {
        message,
        content: encodedContent,
        sha,
        branch
      }
    );

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            status: "success",
            path,
            branch,
            commit: res.data.commit.html_url
          }, null, 2)
        }
      ]
    };
  }

  /*
  TOOL: create_branch
  Creates a new branch from the base branch (usually main)
  */
  if (request.params.name === "create_branch") {

    const { repo, branch, base } = request.params.arguments;

    // Get the SHA of the base branch tip
    const baseRef = await github.get(
      `/repos/${owner}/${repo}/git/ref/heads/${base}`
    );

    const baseSha = baseRef.data.object.sha;

    // Create new branch pointing to that SHA
    await github.post(
      `/repos/${owner}/${repo}/git/refs`,
      {
        ref: `refs/heads/${branch}`,
        sha: baseSha
      }
    );

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            status: "success",
            branch,
            base,
            sha: baseSha
          }, null, 2)
        }
      ]
    };
  }

  /*
  TOOL: create_pr
  Creates a Pull Request from head branch into base branch
  */
  if (request.params.name === "create_pr") {

    const { repo, title, body, head, base } = request.params.arguments;

    const res = await github.post(
      `/repos/${owner}/${repo}/pulls`,
      {
        title,
        body: body || "",
        head,
        base
      }
    );

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            status: "success",
            pr_url: res.data.html_url,
            pr_number: res.data.number,
            title: res.data.title
          }, null, 2)
        }
      ]
    };
  }

});

/*
Start MCP server
*/
const transport = new StdioServerTransport();
await server.connect(transport);
