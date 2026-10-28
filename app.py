import asyncio
import subprocess

import gradio as gr

from reposcout.agent import Agent
from reposcout.config import Config
from reposcout.mcp_client import McpTools
from reposcout.model import Model
from reposcout.repos import resolve

cfg = Config(name="ui")
model = Model([cfg.model, cfg.fallback_model])

EXAMPLES = [
    ["https://github.com/renad-alsaif/image-classification", "What are the steps of the pipeline?"],
    ["https://github.com/SDAIAAcademy/agentic-ai", "Which function calculates permit fees, and how does it work?"],
    ["https://github.com/python-humanize/humanize", "Where is naturalsize defined?"],
    ["https://github.com/pallets/itsdangerous", "Summarize the open bug reports."],
]

CSS = """
.gradio-container {max-width: 900px !important; margin: 0 auto !important;}
#hero {background: linear-gradient(135deg, #4f46e5, #7c3aed 55%, #db2777); border-radius: 18px;
       padding: 34px 28px 28px; text-align: center; margin-top: 12px;}
#hero h1 {color: #fff; font-size: 2.7em; margin: 0;}
#hero p {color: #e0e7ff; font-size: 1.1em; margin: 8px 0 18px;}
#hero span {display: inline-block; background: rgba(255, 255, 255, 0.18); color: #fff; border-radius: 999px;
            padding: 5px 14px; margin: 3px; font-size: 0.9em;}
.card {border: 1px solid var(--border-color-primary); border-radius: 16px !important; padding: 18px !important;
       background: var(--background-fill-secondary);}
#ask-button {background: linear-gradient(135deg, #4f46e5, #7c3aed) !important; color: #fff !important;
             border: none !important; font-weight: 600;}
#answer {border-left: 5px solid #7c3aed; border-radius: 14px; padding: 18px 22px; min-height: 90px;
         background: var(--background-fill-secondary);}
#cancel-button {font-weight: 600;}
#author {text-align: center; color: var(--body-text-color-subdued); padding: 20px 0 6px; font-size: 0.95em;}
#author a {color: #7c3aed; text-decoration: none;}
footer {display: none !important;}
"""

HERO = """
<div id="hero">
  <h1>RepoScout</h1>
  <p>Paste a GitHub repository link, ask a question, and get an answer with the files it came from.</p>
  <span>Reads the code</span><span>Cites the files</span><span>Asks before writing</span><span>Blocks data leaks</span>
</div>
"""

FOOTER = """
<div id="author">
  Author: <b>Renad Alsaif</b> &nbsp;·&nbsp; Contact: <a href="mailto:Renadalsaiif@gmail.com">Renadalsaiif@gmail.com</a>
</div>
"""


def describe(call):
    args = call["args"]
    return {
        "search_code": f"Searched the code for `{args.get('pattern')}`",
        "read_file": f"Read `{args.get('path')}`",
        "list_files": f"Listed the files in `{args.get('path', '.')}`",
        "get_issues": "Read the repository's GitHub issues",
        "get_repo_stats": "Checked the repository's details on GitHub",
        "list_my_repos": "Listed your repositories",
        "create_issue": f"Drafted an issue: \"{args.get('title')}\"",
    }.get(call["name"], f"Used `{call['name']}`")


def how_it_was_found(res):
    lines = [f"{i}. {describe(c)}" for i, c in enumerate(res.tool_calls, 1)] or ["Answered without opening any files."]
    for a in res.approvals:
        if not a["approved"]:
            lines.append("\nRepoScout wanted to open an issue, but you did not allow it.")
    for b in res.blocked:
        lines.append(f"\nBlocked for safety: {b['reason']}.")
    for w in res.writes:
        lines.append(f"\nIssue prepared for {w['args'].get('repo')}. It is saved locally and posted only if live writes are on.")
    lines.append(f"\n<small>{res.steps} steps · {res.tokens:,} tokens · {', '.join(sorted(set(res.models))) or '-'}</small>")
    return "\n".join(lines)


async def run_agent(repo, question, allow_issues):
    async with McpTools() as mcp:
        agent = Agent(cfg, repo, model, mcp, approve=lambda tool, args: allow_issues)
        return await agent.run(question)


def ask(link, question, allow_issues):
    if not link.strip():
        raise gr.Error("Please paste a GitHub repository link.")
    if not question.strip():
        raise gr.Error("Please type a question.")
    try:
        repo = resolve(link)
    except ValueError:
        raise gr.Error("That doesn't look like a GitHub repository link. Use one like https://github.com/owner/name")
    except subprocess.CalledProcessError:
        raise gr.Error("I couldn't download this repository. Check the link and make sure the repository is public.")
    # A fresh event loop per question, so the MCP subprocess also works on Windows.
    res = asyncio.run(run_agent(repo, question, allow_issues))
    if res.stop == "model_error":
        raise gr.Error("The AI model is busy right now (free models are often rate-limited). Please try again in a minute.")
    if res.stop != "final":
        return "I couldn't finish within my step limit. Try a more specific question.", how_it_was_found(res)
    return res.answer, how_it_was_found(res)


with gr.Blocks(title="RepoScout") as demo:
    gr.HTML(HERO)
    with gr.Column(elem_classes="card"):
        link = gr.Textbox(label="Repository link", placeholder="https://github.com/owner/name")
        question = gr.Textbox(label="Your question", placeholder="Where is the training code?", lines=3)
        with gr.Row(equal_height=True):
            allow_issues = gr.Checkbox(label="Allow RepoScout to open a GitHub issue for this question", value=False)
            ask_button = gr.Button("Ask", variant="primary", scale=0, min_width=140, elem_id="ask-button")
            cancel_button = gr.Button("Cancel", variant="stop", scale=0, min_width=110, elem_id="cancel-button")
    gr.Markdown("### Answer")
    answer = gr.Markdown("Your answer will appear here.", elem_id="answer")
    with gr.Accordion("How RepoScout found this", open=False):
        details = gr.Markdown()
    gr.Examples(EXAMPLES, inputs=[link, question], label="Try an example")
    gr.HTML(FOOTER)
    asking = [ask_button.click(ask, [link, question, allow_issues], [answer, details]),
              question.submit(ask, [link, question, allow_issues], [answer, details])]
    cancel_button.click(lambda: ("Cancelled. Ask again whenever you're ready.", ""), None, [answer, details], cancels=asking)

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(primary_hue="indigo"), css=CSS, inbrowser=True)