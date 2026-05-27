import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";
import axios from "axios";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.join(__dirname, "jira-mcp-server", ".env");

console.log("Loading from:", envPath);
const result = dotenv.config({ path: envPath });

console.log("Environment loaded:", !!result.parsed);
console.log("JIRA_DOMAIN:", process.env.JIRA_DOMAIN);
console.log("JIRA_EMAIL:", process.env.JIRA_EMAIL);
console.log("Token length:", process.env.JIRA_API_TOKEN?.length);

const url = `${process.env.JIRA_DOMAIN}/rest/api/3/issue/KAN-4`;
console.log("URL to call:", url);

try {
  const response = await axios.get(url, {
    auth: {
      username: process.env.JIRA_EMAIL,
      password: process.env.JIRA_API_TOKEN
    }
  });
  console.log("Success! Response:", response.status);
} catch (error) {
  console.error("Error:", error.message);
  console.error("Code:", error.code);
  console.error("Response status:", error.response?.status);
}
