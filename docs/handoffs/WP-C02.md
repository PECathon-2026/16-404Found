# WP-C02 - LLM adapter
**Status:** ready-for-review
**Branch:** wp/c02-llm-adapter

## What I built
- `devpilot/llm/anthropic_adapter.py`: `AnthropicLLM` (`LLMPort`), pure `build_params` / `map_response` / `effort_for_budget`.
- `devpilot/llm/pricing.py`: price table + `cost_usd(model, usage_counts)`; unknown model -> 0.0 + warning.
- `devpilot/llm/cassette.py`: `CassetteLLM` (record / replay / passthrough), `CassetteMiss`.
- `devpilot/llm/fake.py`: `ScriptedLLM`, `make_response` helper.
- `tests/llm/` (51 tests, no network), `docs/llm-notes.md` (constraints C03 must know).

## How to verify
```bash
python -m pytest -q tests/llm      # 44 passed
python -m pytest -q                # 51 passed
python -m ruff check devpilot/llm tests/llm   # All checks passed
python -m mypy devpilot/llm        # Success: no issues found in 5 source files
```

## Deviations from spec
- Haiku 5.5 **accepts** forced `tool_choice` per the docs (Haiku section, "Forced tool calls skip thinking"), so the rewrite applies only to Opus/Sonnet 5.5 (and Fable/Mythos 5.1 prefixes); Haiku passes it through.
- `submit_*` tools are `strict` on every Opus/Sonnet request (not only when forced), keeping the `tools` array stable across turns (a changing tools array invalidates replayed thinking blocks and the cache).
- Cassette key hashes the `LLMRequest` (minus `metadata`, tier instead of model id), not the built API params: replay needs no inner adapter/config and survives model remapping.
- Refusal responses return empty `raw_assistant_content` (partial output of a declined turn is to be discarded per docs).
- Haiku long-prompt rate card (>100K prompt tokens: 0.50/2.50, cache 0.05/0.625) added to pricing per the docs; the given table is the <=100K card.
- 529 retry applies only before any text delta was yielded (cannot un-yield text). `max_retries=4` is set only on the client the adapter builds itself; an injected client keeps its own setting.
- `build_params` has an extra keyword `enable_fallbacks`; message `cache_control` markers already present in caller messages count toward the 4-breakpoint cap.
- Docs vs brief: none contradicted the stated facts except Haiku forced tool choice (above).

## Contract change requests
- None required. Suggest (optional) `LLMRequest.tool_choice` doc comment note that forcing is advisory on Opus/Sonnet 5.5, and that `raw_assistant_content` is `[]` on refusal.

## Known gaps
- Fallback-model thinking-block dropping, `stop_details` category, and `fallback` content blocks are passed through in `raw_assistant_content` but not surfaced separately.
- Per-message effort, compaction, and context-editing betas are not implemented (C03 decision; see docs/llm-notes.md).
- Not exercised against the live API (no network in this packet).
