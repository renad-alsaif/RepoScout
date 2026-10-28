"""Run every task in evals/tasks.jsonl on configs A and B.

uv run evals/run_evals.py
uv run evals/run_evals.py --limit 5 --trials 3
uv run evals/run_evals.py --ids repo-license --configs B

GitHub tools run on offline fixtures, writes are dry-run, memory is off and approvals
are granted unless a task sets "approve": false, so the guard in code is what gets tested.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.graders import grade  # noqa: E402
from reposcout.agent import Agent  # noqa: E402
from reposcout.config import Config  # noqa: E402
from reposcout.mcp_client import McpTools  # noqa: E402
from reposcout.model import Model  # noqa: E402
from reposcout.repos import resolve  # noqa: E402

CONFIGS = {
    "A": Config(name="A-no-repo-map", repo_map=False, use_memory=False),
    "B": Config(name="B-repo-map", repo_map=True, use_memory=False),
}


async def run_config(key, tasks, trials, out, sleep):
    cfg = CONFIGS[key]
    model = Model([cfg.model, cfg.fallback_model])
    rows = []
    async with McpTools({"REPOSCOUT_OFFLINE": "1", "REPOSCOUT_LIVE_WRITES": "0"}) as mcp:
        for task in tasks:
            repo = resolve(task["repo"])
            for trial in range(1, trials + 1):
                agent = Agent(cfg, repo, model, mcp, approve=lambda tool, args: task.get("approve", True),
                              trace_dir=out / "traces", run_id=f"{key}-{task['id']}-{trial}")
                res = await agent.run(task["prompt"])
                failures = await grade(task, res, repo.full_name, model)
                rows.append({"config": key, "task": task["id"], "category": task["category"], "trial": trial,
                             "prompt": task["prompt"], "tools": [t["name"] for t in res.tool_calls],
                             "passed": not failures, "failures": failures, "steps": res.steps,
                             "tokens": res.tokens, "stop": res.stop, "answer": res.answer,
                             "trace": agent.trace_path.relative_to(ROOT).as_posix()})
                print(f"{key} {task['id']} trial {trial}: {'PASS' if not failures else 'FAIL ' + '; '.join(failures)}")
                await asyncio.sleep(sleep)
    return rows


def summary(results, trials):
    lines = [f"| Config | Passed | pass^{trials} | Avg steps | Avg tokens | Security passed |",
             "|---|---|---|---|---|---|"]
    for key, rows in results.items():
        tasks = {r["task"] for r in rows}
        all_trials_passed = sum(all(r["passed"] for r in rows if r["task"] == t) for t in tasks)
        security = [r for r in rows if r["category"] == "security"]
        lines.append(f"| {key} ({CONFIGS[key].name}) | {sum(r['passed'] for r in rows)}/{len(rows)} "
                     f"| {all_trials_passed}/{len(tasks)} | {sum(r['steps'] for r in rows) / len(rows):.1f} "
                     f"| {sum(r['tokens'] for r in rows) / len(rows):,.0f} "
                     f"| {sum(r['passed'] for r in security)}/{len(security)} |")
    lines += ["", "## Details"]
    all_rows = [r for rows in results.values() for r in rows]
    for task_id in dict.fromkeys(r["task"] for r in all_rows):
        task_rows = [r for r in all_rows if r["task"] == task_id]
        lines += ["", f"### {task_id}", f"**Question:** {task_rows[0]['prompt']}"]
        for r in task_rows:
            verdict = "PASS" if r["passed"] else "FAIL: " + "; ".join(r["failures"])
            lines += ["", f"**{r['config']}** trial {r['trial']}: {verdict}",
                      f"- steps {r['steps']}, tokens {r['tokens']:,}, stop: {r['stop']}",
                      f"- tools: {' -> '.join(r['tools']) or 'none'}",
                      f"- trace: `{r['trace']}`",
                      "- answer:", "", "> " + (r["answer"] or "(empty)").replace("\n", "\n> ")]
    return "\n".join(lines)


async def main(args):
    tasks = [json.loads(line) for line in (ROOT / "evals" / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    tasks = [t for t in tasks if not args.ids or t["id"] in args.ids][:args.limit]
    if not tasks:
        raise SystemExit("No tasks yet. Add them to evals/tasks.jsonl")
    out = ROOT / "results" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    results = {key: await run_config(key, tasks, args.trials, out, args.sleep) for key in args.configs}
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for rows in results.values() for r in rows)
    report = summary(results, args.trials)
    (out / "summary.md").write_text(report + "\n", encoding="utf-8")
    print(f"\n{report.split('## Details')[0]}\nSaved to {out.relative_to(ROOT).as_posix()}/summary.md")


parser = argparse.ArgumentParser()
parser.add_argument("--configs", nargs="+", default=["A", "B"], choices=list(CONFIGS))
parser.add_argument("--trials", type=int, default=1)
parser.add_argument("--limit", type=int)
parser.add_argument("--ids", nargs="+", help="run only these task ids")
parser.add_argument("--sleep", type=float, default=2.0, help="seconds between tasks, for rate limits")
asyncio.run(main(parser.parse_args()))
