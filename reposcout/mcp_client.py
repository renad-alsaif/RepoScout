import os
import sys

from mcp import Client, StdioServerParameters

from .config import ROOT

# The MCP server gets the GitHub token but never the model API key.
PASS_ENV = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "HTTPS_PROXY", "SSL_CERT_FILE",
            "GITHUB_TOKEN", "REPOSCOUT_OFFLINE", "REPOSCOUT_LIVE_WRITES")


class McpTools:
    def __init__(self, extra_env=None):
        env = {k: os.environ[k] for k in PASS_ENV if k in os.environ} | (extra_env or {})
        self.client = Client(StdioServerParameters(
            command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py")], env=env))
        self.schemas = []
        self.names = set()

    async def __aenter__(self):
        await self.client.__aenter__()
        for t in (await self.client.list_tools()).tools:
            self.names.add(t.name)
            self.schemas.append({"type": "function", "function": {
                "name": t.name, "description": t.description or "", "parameters": t.input_schema}})
        return self

    async def __aexit__(self, *exc):
        await self.client.__aexit__(*exc)

    async def call(self, name, args):
        res = await self.client.call_tool(name, args)
        return "\n".join(getattr(c, "text", "") for c in res.content), res.is_error
