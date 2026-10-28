import json
import time
from dataclasses import dataclass, field

from .config import ROOT, WRITE_TOOLS
from .guard import Guard
from .tools import LOCAL_TOOLS, SCHEMAS, RepoTools

AGENTS_MD = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
MEMORY = ROOT / "memory.json"


@dataclass
class Result:
    answer: str = ""
    stop: str = "max_steps"
    steps: int = 0
    tokens: int = 0
    tool_calls: list = field(default_factory=list)
    approvals: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    writes: list = field(default_factory=list)
    models: list = field(default_factory=list)


def ask_user(tool, args):
    print(f"\nAPPROVAL NEEDED: {tool}\n{json.dumps(args, indent=2, ensure_ascii=False)}")
    return input("Allow? [y/N] ").strip().lower() == "y"


def untrusted(text):
    return f'<tool_output trust="untrusted">\n{text}\n</tool_output>'


def load_memory():
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_memory(repo, text):
    memory = load_memory()
    memory.pop(repo, None)
    memory[repo] = " ".join(text.split())[:600]
    MEMORY.write_text(json.dumps(dict(list(memory.items())[-20:]), indent=2, ensure_ascii=False), encoding="utf-8")


class Agent:
    def __init__(self, cfg, repo, model, mcp, approve=ask_user, trace_dir=ROOT / "runs" / "traces", run_id=None):
        self.cfg, self.repo, self.model, self.mcp, self.approve = cfg, repo, model, mcp, approve
        self.local = RepoTools(repo.path)
        self.guard = Guard(repo.full_name)
        self.tools = SCHEMAS + mcp.schemas
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = trace_dir / f"{run_id or time.strftime('%Y%m%d-%H%M%S')}.jsonl"

    def log(self, event, **data):
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": round(time.time(), 2), "event": event, **data}, ensure_ascii=False) + "\n")

    def system_prompt(self):
        parts = [AGENTS_MD, f"Target repository: {self.repo.full_name}. Use this name as the repo argument for GitHub tools."]
        if self.cfg.repo_map:
            parts.append("Repo map (files and top-level names):\n" + untrusted(self.local.repo_map()))
        if self.cfg.use_memory and (note := load_memory().get(self.repo.full_name)):
            parts.append("Notes from an earlier session, may be outdated:\n" + untrusted(note))
        return "\n\n".join(parts)

    def compact(self, messages):
        if sum(len(json.dumps(m)) for m in messages) // 4 <= self.cfg.compact_after:
            return
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        old = [m for m in tool_msgs[:len(tool_msgs) - self.cfg.keep_recent] if not m["content"].startswith("[compacted]")]
        for m in old:
            first_line = (m["content"].splitlines()[1:2] or [""])[0][:120]
            m["content"] = f"[compacted] earlier result starting: {first_line}"
        if old:
            self.log("compaction", count=len(old))

    async def run_tool(self, call, res):
        name = call["name"]
        try:
            args = json.loads(call["arguments"] or "{}")
        except json.JSONDecodeError:
            return "ERROR: arguments are not valid JSON"
        if not isinstance(args, dict):
            return "ERROR: arguments must be a JSON object"
        res.tool_calls.append({"name": name, "args": args})
        self.log("tool_call", tool=name, args=args)

        if name in WRITE_TOOLS:
            if self.cfg.guard and (reason := self.guard.check(name, args)):
                res.blocked.append({"tool": name, "args": args, "reason": reason})
                self.log("guard_block", tool=name, reason=reason)
                return f"BLOCKED: {reason}. Do not retry, tell the user."
            approved = self.approve(name, args)
            res.approvals.append({"tool": name, "approved": approved})
            self.log("approval", tool=name, approved=approved)
            if not approved:
                return "DENIED by the user. Do not retry."

        try:
            if name in self.mcp.names:
                text, failed = await self.mcp.call(name, args)
                text = "ERROR: " + text if failed else text
            elif name in LOCAL_TOOLS:
                text = getattr(self.local, name)(**args)
            else:
                text = f"ERROR: unknown tool {name}"
        except Exception as e:
            text = f"ERROR: {e}"

        if name in WRITE_TOOLS and not text.startswith("ERROR"):
            res.writes.append({"tool": name, "args": args})
        self.guard.observe(name, text)
        if len(text) > self.cfg.max_tool_chars:
            text = text[:self.cfg.max_tool_chars] + "\n(truncated, narrow your request)"
        self.log("tool_result", tool=name, chars=len(text), preview=text[:200])
        return untrusted(text)

    async def run(self, question):
        res = Result()
        messages = [{"role": "system", "content": self.system_prompt()}, {"role": "user", "content": question}]
        self.log("start", config=self.cfg.name, model=self.cfg.model, repo=self.repo.full_name, question=question)

        for step in range(1, self.cfg.max_steps + 1):
            if res.tokens >= self.cfg.max_tokens:
                res.stop = "token_budget"
                break
            self.compact(messages)
            try:
                reply = await self.model.chat(messages, self.tools)
            except Exception as e:
                res.stop, res.answer = "model_error", str(e)
                break
            res.steps, res.tokens = step, res.tokens + reply.tokens
            res.models.append(reply.model)
            self.log("model_call", step=step, model=reply.model, tokens=reply.tokens,
                     tool_calls=[c["name"] for c in reply.tool_calls])
            if not reply.tool_calls:
                res.stop, res.answer = "final", reply.content.strip()
                break
            messages.append({"role": "assistant", "content": reply.content, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in reply.tool_calls]})
            for c in reply.tool_calls:
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": await self.run_tool(c, res)})

        if res.stop in ("max_steps", "token_budget"):
            res.answer = f"Stopped ({res.stop}) after {res.steps} steps and {res.tokens} tokens."
        if self.cfg.use_memory and res.stop == "final":
            save_memory(self.repo.full_name, res.answer)
        self.log("end", stop=res.stop, steps=res.steps, tokens=res.tokens,
                 blocked=len(res.blocked), writes=len(res.writes), answer=res.answer[:500])
        return res
