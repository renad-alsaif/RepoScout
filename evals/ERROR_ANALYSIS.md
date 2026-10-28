# Error analysis

## Runs

| Run | Tasks | Result | Notes |
|---|---|---|---|
| First full run | 20 × A and B | A 19/20, B 19/20 | One failure in each configuration: `ai-fee-function` |
| Final run (after the grader fix) | 20 × A and B | A 20/20, B 20/20 | All tasks passed |

Model: `nvidia/nemotron-3.5-super-vl:free`, fallback `nvidia/nemotron-3-ultra-550b-a55b:free`, 1 trial per task, 28 October 2026.

## Failures and root causes

### 1. `ai-fee-function`: ambiguous question, grader too strict

- **Symptom:** failed in both configurations in the first run, with "missing ['fee_for', 'madar.py']".
- **Root cause:** the question "Which function calculates permit fees, and in which file is it?" has several correct answers. The course repository contains four fee functions:

  | Function | File |
  |---|---|
  | `fee_for` | `labs/madar.py` |
  | `compute_fee` | `labs/madar.py` (method of the `Madar` class) |
  | `permit_fee` | `labs/data/madar_fees/madar_fees/fees.py` |
  | `fee` | `labs/prepare_data.py` |

  The grader accepted only `fee_for` in `madar.py`.
- **Fix:** the grader now accepts any of `fee_for`, `compute_fee` or `permit_fee`, together with `madar.py` or `fees.py`. The question did not change.
- **Result:** passes in both configurations in the final run.

## Grader review

Each grader was checked against plausible wrong answers.

- **`ic-split` is weaker than it looks.** It uses `contains_all` with `70` and `15`, which only checks that each number appears once. A wrong answer such as 70/15/20 would pass. The agent's answers were correct (70/15/15), but a stricter check (a pattern requiring 70, 15 and 15 in order) would be better.
- **Judge tasks** (`ai-ralph-stop`, `ic-missing`, `scope-off-topic`, `scope-off-topic-ar`) are graded by the same model family that answers, so a lenient judge could pass a weak answer. Their answers were read by hand in the summary and were correct.

## Reliability

- The primary model timed out on several tasks in both runs. Each model call has a 90-second timeout, one retry, then the fallback model. Every timeout was recovered, so no task ended with `stop: model_error`.
- Earlier, partial runs were stopped by OpenRouter's free daily limit (50 requests). Those runs exposed three issues in the eval runner: results were saved only at the end of a run, a failing judge call stopped the whole run, and a task whose model never answered could pass a "tool not called" check. The final results come from complete runs with no model errors, so they were not affected.

## The change from A to B

- **Change:** config B gives the model a repo map (files plus top-level functions and classes) before it starts. Nothing else differs.
- **Effect:** same accuracy (20/20 in both), 29% fewer steps (3.4 to 2.4) and 8% fewer tokens (8,797 to 8,101).
- **Why:** without the map, the agent usually searches or lists files before reading the right one. With the map it can open the right file directly. The token saving is smaller than the step saving because the map is added to every prompt.
- **Next change I would try:** asking the model to request several files in one step, which should cut steps further on multi-file questions.