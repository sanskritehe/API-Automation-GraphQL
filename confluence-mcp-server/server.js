import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ListToolsRequestSchema, CallToolRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import axios from "axios";
import dotenv from "dotenv";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dotEnvPath = path.join(__dirname, ".env");
const envPath = path.join(__dirname, "env");
const resolvedEnvPath = fs.existsSync(dotEnvPath) ? dotEnvPath : envPath;
dotenv.config({ path: resolvedEnvPath });

/*
Initialize MCP Server
*/
const server = new Server(
  {
    name: "confluence-mcp-server",
    version: "1.0.0"
  },
  {
    capabilities: { tools: {} }
  }
);

/*
Helper: Strip HTML tags from Confluence storage format
*/
function stripHtml(html) {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/*
Generate Confluence Authorization Header
*/
function getAuthHeader() {
  const token = Buffer.from(
    `${process.env.CONFLUENCE_EMAIL}:${process.env.CONFLUENCE_API_TOKEN}`
  ).toString("base64");

  return `Basic ${token}`;
}

/*
List available tools
*/
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "get_confluence_page",
      description: "Fetch a Confluence page by title from a given space and return its plain text content",
      inputSchema: {
        type: "object",
        properties: {
          spaceKey: {
            type: "string",
            description: "The Confluence space key e.g. hpeteam2"
          },
          title: {
            type: "string",
            description: "The exact title of the Confluence page"
          }
        },
        required: ["spaceKey", "title"]
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
  Tool: get_confluence_page
  */
  if (request.params.name === "get_confluence_page") {

    const { spaceKey, title } = request.params.arguments;

    try {

      const url = `${process.env.CONFLUENCE_DOMAIN}/wiki/rest/api/content`;

      const response = await axios.get(url, {
        headers: {
          Authorization: getAuthHeader(),
          Accept: "application/json"
        },
        params: {
          title,
          spaceKey,
          expand: "body.storage"
        }
      });

      const results = response.data.results;

      if (!results || results.length === 0) {
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                error: "Page not found",
                spaceKey,
                title
              }, null, 2)
            }
          ]
        };
      }

      const page = results[0];
      const rawHtml = page.body.storage.value;
      const plainText = stripHtml(rawHtml);

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              title: page.title,
              spaceKey,
              url: `${process.env.CONFLUENCE_DOMAIN}/wiki${page._links.webui}`,
              content: plainText
            }, null, 2)
          }
        ]
      };

    } catch (error) {

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              error: "Failed to fetch Confluence page",
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
