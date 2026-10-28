"""GitHub tools over MCP (stdio).

Without GITHUB_TOKEN (or with REPOSCOUT_OFFLINE=1) it reads fixtures/github/ instead of the API.
create_issue only saves to runs/outbox.jsonl unless REPOSCOUT_LIVE_WRITES=1.
Approval and the guard are in the agent, not here.
"""

import json
import os
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.getenv("GITHUB_TOKEN", "")
OFFLINE = os.getenv("REPOSCOUT_OFFLINE") == "1" or not TOKEN
LIVE_WRITES = os.getenv("REPOSCOUT_LIVE_WRITES") == "1"

mcp = MCPServer("reposcout-github")


def fixture(name):
    path = ROOT / "fixtures" / "github" / f"{name}.json"
    if not path.exists():
        raise ToolError(f"No offline data for {name}. Add GITHUB_TOKEN to .env for live GitHub data.")
    return json.loads(path.read_text(encoding="utf-8"))


def github(method, path, **kwargs):
    import httpx

    try:
        r = httpx.request(method, f"https://api.github.com{path}", timeout=20, **kwargs,
                          headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"})
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ToolError(f"GitHub API returned {e.response.status_code} for {path}")
    except httpx.HTTPError as e:
        raise ToolError(f"GitHub API request failed: {type(e).__name__}")
    return r.json()


def check_repo(repo):
    repo = repo.strip().removeprefix("https://github.com/").strip("/")
    if repo.count("/") != 1:
        raise ToolError("repo must look like owner/name")
    return repo


@mcp.tool()
def list_my_repos() -> str:
    """List the user's repositories, including private ones."""
    if OFFLINE:
        return json.dumps(fixture("my_repos"))
    return json.dumps({"repos": [{"full_name": r["full_name"], "private": r["private"]}
                                 for r in github("GET", "/user/repos", params={"per_page": 50})]})


@mcp.tool()
def get_repo_stats(repo: str) -> str:
    """Get a repository's description, language, license, open issues and last push."""
    repo = check_repo(repo)
    if OFFLINE:
        return json.dumps(fixture(repo.replace("/", "__"))["stats"])
    r = github("GET", f"/repos/{repo}")
    return json.dumps({"full_name": r["full_name"], "description": r.get("description"),
                       "language": r.get("language"), "license": (r.get("license") or {}).get("spdx_id"),
                       "open_issues": r.get("open_issues_count"), "pushed_at": r.get("pushed_at")})


@mcp.tool()
def get_issues(repo: str, label: str | None = None, state: str = "open") -> str:
    """List a repository's issues, optionally filtered by label."""
    repo = check_repo(repo)
    if OFFLINE:
        issues = [i for i in fixture(repo.replace("/", "__"))["issues"]
                  if (state == "all" or i["state"] == state) and (not label or label in i["labels"])]
    else:
        params = {"state": state, "per_page": 20} | ({"labels": label} if label else {})
        issues = [{"number": i["number"], "title": i["title"], "labels": [l["name"] for l in i["labels"]],
                   "state": i["state"], "body": (i.get("body") or "")[:1500]}
                  for i in github("GET", f"/repos/{repo}/issues", params=params) if "pull_request" not in i]
    return json.dumps({"repo": repo, "issues": issues[:20]})


@mcp.tool()
def create_issue(repo: str, title: str, body: str) -> str:
    """Create an issue on a repository. This is a public write."""
    repo = check_repo(repo)
    if not LIVE_WRITES:
        (ROOT / "runs").mkdir(exist_ok=True)
        with (ROOT / "runs" / "outbox.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.time(), "repo": repo, "title": title, "body": body}) + "\n")
        return json.dumps({"status": "dry_run", "repo": repo, "note": "Saved to runs/outbox.jsonl, not posted."})
    r = github("POST", f"/repos/{repo}/issues", json={"title": title, "body": body})
    return json.dumps({"status": "created", "url": r.get("html_url")})


if __name__ == "__main__":
    mcp.run()
