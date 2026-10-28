import argparse
import asyncio

from reposcout.agent import Agent
from reposcout.config import Config
from reposcout.mcp_client import McpTools
from reposcout.repos import clone_pinned, registry, resolve


async def ask(args):
    from reposcout.model import Model

    cfg = Config(name="cli", max_steps=args.max_steps, repo_map=not args.no_repo_map,
                 use_memory=not args.no_memory, guard=not args.no_guard)
    if not cfg.guard:
        print("WARNING: guard is OFF")
    model = Model([cfg.model, cfg.fallback_model])
    try:
        repo = resolve(args.repo)
    except ValueError as e:
        raise SystemExit(e)
    async with McpTools() as mcp:
        agent = Agent(cfg, repo, model, mcp)
        res = await agent.run(args.question)
    print("\n" + res.answer)
    print(f"\n--- {res.stop} | steps {res.steps} | tokens {res.tokens} | blocked {len(res.blocked)} "
          f"| writes {len(res.writes)} | model {', '.join(sorted(set(res.models)))}")
    for b in res.blocked:
        print(f"GUARD BLOCKED {b['tool']}: {b['reason']}")
    print(f"trace: {agent.trace_path}")


parser = argparse.ArgumentParser(prog="reposcout")
sub = parser.add_subparsers(dest="command", required=True)
sub.add_parser("setup", help="clone the repos in repos.toml")
ask_parser = sub.add_parser("ask")
ask_parser.add_argument("--repo", required=True, help="name from repos.toml, owner/name, or GitHub URL")
ask_parser.add_argument("question")
ask_parser.add_argument("--max-steps", type=int, default=10)
ask_parser.add_argument("--no-repo-map", action="store_true")
ask_parser.add_argument("--no-memory", action="store_true")
ask_parser.add_argument("--no-guard", action="store_true", help="turn off the guard, attack demo only")
args = parser.parse_args()

if args.command == "setup":
    for r in registry().values():
        print("ready:", clone_pinned(r))
else:
    asyncio.run(ask(args))
