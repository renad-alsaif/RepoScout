import json
import os
import re

SECRETS = [re.compile(p) for p in (
    r"gh[pousr]_\w{20,}",
    r"github_pat_\w{20,}",
    r"sk-or-[\w-]{16,}",
    r"sk-\w{32,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)]


class Guard:
    def __init__(self, target_repo):
        self.target = target_repo.lower()
        self.private = {v for v in (os.getenv("GITHUB_TOKEN", ""), os.getenv("OPENROUTER_API_KEY", "")) if len(v) >= 8}

    def observe(self, tool, result):
        if tool != "list_my_repos":
            return
        try:
            repos = json.loads(result)["repos"]
        except (json.JSONDecodeError, KeyError):
            return
        for r in repos:
            if r["private"]:
                self.private |= {r["full_name"], r["full_name"].split("/")[1]}

    def check(self, tool, args):
        if tool != "create_issue":
            return f"no policy for {tool}"
        repo = str(args.get("repo", "")).removeprefix("https://github.com/").strip("/").lower()
        if repo != self.target:
            return f"issues can only be created on {self.target}, not {args.get('repo')}"
        text = f"{args.get('title', '')}\n{args.get('body', '')}"
        if len(text) > 5000:
            return "issue text is too long"
        if any(rx.search(text) for rx in SECRETS):
            return "issue text contains a token or key"
        if any(v.lower() in text.lower() for v in self.private):
            return "issue text contains private data seen in this session"
        return None
