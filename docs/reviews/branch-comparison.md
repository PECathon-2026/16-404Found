# DevPilot branch evaluation — partial comparison

Evaluated on 2026-10-30 against the user-supplied DevPilot masterplan and hackathon submission requirements. Scores measure demonstrated working behavior, rather than the number of implemented files.

## Fetch and scope

`git fetch --all --prune` failed with `Could not resolve host: github.com`. `git ls-remote --heads origin` also failed. No remote contribution was pulled successfully in this evaluation.

On the user's follow-up request, separate remote `git clone --single-branch --branch ...` commands were attempted for all three branches. All failed with the same DNS error. A separate clone of the cached `siddharth` branch was successfully created from the existing local repository at `<isolated-review>/siddharth`, using `--no-hardlinks`. Its commit is the same `33080b9`; this does not establish remote freshness. The core suite and mini-shop suite were rerun in this new clone and again produced 37 passed and 8 passed, respectively. The independent regression suite was copied with only its import path adjusted to the new clone and again produced 14 failed.

The local clone is `.`. Its cached `siddharth` ref points to `33080b9021239c0a0e3d87adbf46820329234bd6`. Neither `imp1` nor `wp/g08-fixtures` exists in its local or cached remote refs. A search of Documents and Downloads found no other copy of this repository containing those branches.

The cached commit is not verified as the current remote tip. The score below therefore applies only to the inspected commit. The local, untracked `frontend/` is separate work and is excluded from branch scoring.

## Results

| Branch | Score / 10 | Working status |
| --- | --- | --- |
| `siddharth` — cached `33080b9` | **3.0** | Basic tests pass; core lifecycle, safety, and approval checks fail. Not reliable end to end. |
| `imp1` | **Unrated** | Branch contents unavailable; not executed or reviewed. |
| `wp/g08-fixtures` | **Unrated** | Branch contents unavailable; not executed or reviewed. |

**Best branch:** undetermined until the other branches can be inspected. The available `siddharth` version cannot be recommended as a working submission. Lack of access to a branch is not treated as a zero score or evidence of defects.

## Strict scoring rubric

| Criterion | Maximum | Cached `siddharth` | Reason |
| --- | ---: | ---: | --- |
| End-to-end mission execution | 3.00 | 0.50 | Task completion and step accounting prevent the normal workflow from progressing. |
| Safety, isolation, approval, and apply | 2.00 | 0.25 | Simple block cases pass, but command/path escapes, an incomplete gate, and whole-snapshot apply violate essential requirements. |
| Independent verification, review, and repair | 1.50 | 0.25 | Agent/tool structure exists; successful criteria, findings resolution, re-review, and current-evidence handling are incomplete. |
| Tests and evaluation evidence | 1.50 | 0.75 | Core tests pass. Scenario/comparison logic is unreliable and no successful real model mission was verified. |
| Judge-facing experience and setup | 1.00 | 0.50 | Dashboard and documentation exist; default Live View and provider/setup inconsistencies impair the demo. |
| Architecture and code organization | 1.00 | 0.75 | Clear four-agent modular structure and typed shared state; enforcement and state transitions remain incomplete. |
| **Total** | **10.00** | **3.00** | **An implemented prototype with broken essential behavior.** |

## Checks rerun during this evaluation

Execution used the previously isolated review copy corresponding to the cached commit, with its installed temporary virtual environment. Model calls in the independent checks are explicitly mocked; file and command operations are real and use synthetic temporary fixtures. These checks are not an actual AI mission or judge-facing mission evidence.

| Check | Actual result |
| --- | --- |
| `python -m pytest tests/ -q -p no:cacheprovider` | 37 passed, 1 collection warning |
| mini-shop `python -m pytest tests/ -q -p no:cacheprovider` | 8 passed |
| Independent review regression suite | 14 failed |

The independent checks reproduce:

1. Workspace-prefix sibling paths accepted.
2. Synthetic `.env` file readable.
3. Search following a symlink outside the workspace.
4. Shell separator accepted and executed.
5. Command reading a synthetic file outside the workspace.
6. Developer completion leaving a task pending.
7. One short invocation consuming the entire agent budget.
8. Successful independent check leaving its criterion unmet.
9. A later `ls` hiding a failed test suite.
10. Approval requested with an unmet criterion.
11. Apply overwriting unrelated user edits with stale snapshot content.
12. A historical finding continuing to force repair after success.
13. Clarification failing to resume planning after an answer.
14. Scenario status comparison using enum formatting rather than its value.

The detailed existing review is [DevPilot-siddharth-review.md](siddharth-review.md). The independent tests are in `docs/reviews/test_review_regressions.py`.

## What is needed to finish the comparison

Fetch the remote refs from a terminal with GitHub access, or provide a local clone containing `imp1` and `wp/g08-fixtures`. Then compare exact commit hashes in isolated checkouts, run the same applicable safety/lifecycle checks, validate deterministic scenarios, and inspect any genuine mission logs. An API-enabled live run is needed before claiming that a branch works end to end with real agents.

No project source was changed, no branches were merged, and the frontend work was preserved.

The subsequent [complete known-error catalogue](errors-33080b9.md) expands the review to 40 separately described findings. Its regression suite has 15 failing checks after adding a reproduced model tool-loop continuation defect; fresh raw outputs and dashboard timeout evidence are included there. The original 14-check results above refer to the earlier comparison run.
