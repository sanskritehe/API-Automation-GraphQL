import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ListToolsRequestSchema, CallToolRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import axios from "axios";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, ".env") });

/*
Initialize MCP Server
*/
const server = new Server(
  {
    name: "jira-mcp-server",
    version: "1.0.0"
  },
  {
    capabilities: { tools: {} }
  }
);

/*
Helper: Extract plain text from Jira rich text format
*/
function parseDescription(desc) {
  if (!desc || !desc.content) return "No description";

  try {
    return desc.content
      .map(block =>
        block.content
          ? block.content.map(text => text.text || "").join("")
          : ""
      )
      .join("\n");
  } catch {
    return "Unable to parse description";
  }
}

/*
Generate Jira Authorization Header
*/
function getAuthHeader() {
  const token = Buffer.from(
    `${process.env.JIRA_EMAIL}:${process.env.JIRA_API_TOKEN}`
  ).toString("base64");

  return `Basic ${token}`;
}

/*
List available tools
*/
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "get_jira_issue",
      description: "Fetch detailed Jira issue information by issue key",
      inputSchema: {
        type: "object",
        properties: {
          issueKey: {
            type: "string",
            description: "Jira issue key like KAN-1"
          }
        },
        required: ["issueKey"]
      }
    },
    {
      name: "add_jira_comment",
      description: "Add a comment to a Jira issue",
      inputSchema: {
        type: "object",
        properties: {
          issueKey: {
            type: "string",
            description: "Jira issue key like KAN-1"
          },
          body: {
            type: "string",
            description: "Plain text content of the comment"
          }
        },
        required: ["issueKey", "body"]
      }
    },
    {
      name: "ping",
      description: "Health check tool that returns pong",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false
      }
    }
  ]
}));

/*
Handle tool execution
*/
server.setRequestHandler(CallToolRequestSchema, async (request) => {

  /*
  Tool: get_jira_issue
  */
  if (request.params.name === "get_jira_issue") {

    const issueKey = request.params.arguments.issueKey;

    try {

      const url = `${process.env.JIRA_DOMAIN}/rest/api/3/issue/${issueKey}`;

      console.error("DEBUG URL:", url);

      const response = await axios.get(url, {
        headers: {
          Authorization: getAuthHeader(),
          Accept: "application/json"
        }
      });

      const issue = response.data;

      const issueData = {
        key: issue.key,

        summary: issue.fields.summary,

        description: parseDescription(issue.fields.description),

        status: issue.fields.status?.name || null,

        priority: issue.fields.priority?.name || null,

        issueType: issue.fields.issuetype?.name || null,

        assignee: issue.fields.assignee
          ? {
              name: issue.fields.assignee.displayName,
              email: issue.fields.assignee.emailAddress
            }
          : null,

        reporter: issue.fields.reporter
          ? {
              name: issue.fields.reporter.displayName,
              email: issue.fields.reporter.emailAddress
            }
          : null,

        labels: issue.fields.labels || [],

        created: issue.fields.created,

        updated: issue.fields.updated,

        project: {
          key: issue.fields.project.key,
          name: issue.fields.project.name
        }
      };

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(issueData, null, 2)
          }
        ]
      };

    } catch (error) {

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              error: "Failed to fetch Jira issue",
              status: error.response?.status,
              details: error.response?.data || error.message
            }, null, 2)
          }
        ]
      };

    }
  }

  /*
  Tool: add_jira_comment
  */
  if (request.params.name === "add_jira_comment") {

    const { issueKey, body } = request.params.arguments;

    try {

      const url = `${process.env.JIRA_DOMAIN}/rest/api/3/issue/${issueKey}/comment`;

      await axios.post(url, {
        body: {
          type: "doc",
          version: 1,
          content: [
            {
              type: "paragraph",
              content: [{ type: "text", text: body }]
            }
          ]
        }
      }, {
        headers: {
          Authorization: getAuthHeader(),
          "Content-Type": "application/json",
          Accept: "application/json"
        }
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ status: "success", issueKey }, null, 2)
          }
        ]
      };

    } catch (error) {

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              error: "Failed to add comment",
              status: error.response?.status,
              details: error.response?.data || error.message
            }, null, 2)
          }
        ]
      };

    }
  }

  /*
  Tool: ping
  */
  if (request.params.name === "ping") {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            status: "pong",
            timestamp: new Date().toISOString()
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