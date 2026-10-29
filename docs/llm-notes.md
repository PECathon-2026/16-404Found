# LLM notes (C02) - API constraints for Claude Opus 5.5 / Sonnet 5.5 / Haiku 5.5

Sources: `claude-api` skill docs - `shared/model-migration.md` (sections "Migrating to Claude Opus 5.5",
"Migrating to Claude Sonnet 5.5", "Migrating to Claude Haiku 5.5", "`refusal` stop reason" under the
Fable 5.1 migration, "New API features" under "Migrating to Claude Opus 5"), `shared/tool-use-concepts.md`,
`python/claude-api/tool-use.md`, `shared/prompt-caching.md`.

## What the adapter (`devpilot/llm/anthropic_adapter.py`) does

| Constraint | Handling |
|---|---|
| Forced `tool_choice` (`tool`/`any`) is a 400 on Opus 5.5 and Sonnet 5.5 | Sent as `{"type":"auto"}`; the forced tool is `strict: true` (schema gets `additionalProperties:false`); the adapter does **not** add the instruction. **Adapter never mutates messages; the runtime owns the submit instruction:** C03 appends `submit_instruction(name)` (a user text block) to its own history before the request when `needs_submit_instruction(req, model)` is true, so the text stays in the transcript. Haiku 5.5 accepts forcing, so it is passed through untouched. |
| `budget_tokens` / `disabled` thinking / sampling params are 400s | `thinking={"type":"adaptive","display":"summarized"}`, `output_config.effort` always sent: budget None/<=4000 low, <=8000 medium, <=12000 high, else xhigh. No temperature/top_p/top_k. |
| Thinking blocks must be replayed unchanged | `LLMResponse.raw_assistant_content` is `block.model_dump(mode="json", exclude_none=True)` of every block, in order (empty-text thinking blocks kept). `build_params` deep-copies history and never edits it. |
| Refusal = HTTP 200 `stop_reason:"refusal"` | Checked first; response has empty text/tools and **empty `raw_assistant_content`** (do not append it to history). Opus/Sonnet send `fallbacks:"default"` with beta `server-side-fallback-2026-07-01` (typed param on `client.beta.messages` in SDK 2.3.0); Haiku never does (it 400s on a list). Disable with `enable_fallbacks=False`. |
| 4 cache breakpoints max | `PromptBlock/ToolSchema(cache=True)` -> `cache_control: ephemeral`. Counting also includes markers already present in message blocks; the last 4 in render order (tools, system, messages) are kept, earlier ones dropped with a warning; only tool/system markers are ever removed (message content is never altered). |
| Endpoint | Beta endpoint iff `params` has `betas` (`uses_beta`) - one place. |
| Overload | SDK `max_retries=4` (when the adapter builds the client) plus up to 3 extra retries of 529 with exponential backoff + jitter, only before any text was streamed. 400/401/403/404 never retried. |

`submit_*` tools are marked `strict` on every request to Opus/Sonnet 5.5, not just the forced one, so the
`tools` array stays byte-identical turn to turn (see below).

## What the AgentRuntime (C03) must know

1. **Submit cannot be forced.** The adapter nudges with `auto` + instruction, but the model may still end
   its turn without calling `submit_*`. C03 must check `tool_uses` and run its own repair/retry round.
   Append `submit_instruction(name)` to the runtime's own history (permanently) when `needs_submit_instruction` is true; retries append a new nudge rather than editing anything. Call `assert_append_only(prev, new)` (`devpilot/llm/history.py`) before each request in debug/test mode.
2. **History is append-only.** Thinking blocks are bound to the exact prefix (`system`, `tools`, every
   earlier message) and, on accounts created on/after 2026-08-31, a replayed block after any edit is a
   400 (Opus 5.5 "Breaking change 3: thinking blocks are tied to the model and the conversation";
   Haiku 5.5 "Breaking change 5"). Therefore C03 must NOT compact by rewriting/removing earlier turns,
   swap tools mid-conversation, or inject-then-delete reminders. Append the `raw_assistant_content` as is.
   The submit instruction must be in stored history; the adapter will not inject it.
3. **Compaction:** use server-side compaction / context editing instead (on-demand `compaction`
   parameter, beta `compact-2026-09-04`; or threshold compaction; or context editing / tool-result
   clearing), or client-side *simple* compaction that replaces the entire history with a summary and
   replays no earlier thinking (a fresh conversation). Per-turn reminders: append, never delete (use a
   text block after the `tool_result` blocks). Tools: declare the full set from turn 1.
4. Changing top-level `effort` between requests invalidates the prompt cache; per-mode effort is fine
   because each mode is its own conversation, but avoid varying it within one.
5. A fallback model runs without the original model's thinking blocks; the API drops them for you.
6. Size `max_output_tokens` for thinking + reply (thinking counts toward `max_tokens`; docs suggest up to
   64K for long agentic turns). `stop_reason=="max_tokens"` after only a thinking block is possible.
7. Text between tool calls may arrive as `thinking` blocks (summarized display) - read blocks by type.
8. Haiku 5.5 bills a higher rate card above 100K prompt tokens; `pricing.cost_usd` applies it.

## Offline tooling

* `CassetteLLM(inner, path, mode)` - JSONL record/replay keyed by sha256 of the canonical request.
* `ScriptedLLM([...])` / `make_response(...)` - fakes for unit tests of other packets.
