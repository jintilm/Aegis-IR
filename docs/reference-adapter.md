# Reference adapter protocol

Adapters live **outside** this repository. That is deliberate: an adapter imports
a network client and reads an API key, and neither belongs in the tree or in CI.
This document is the contract a published result must satisfy, so someone else
can rebuild an equivalent adapter and check the numbers.

The harness itself is vendor-neutral: it hands `solve(task, workspace)` a
workspace containing only the task's visible files (plus the oracle shim for
binary-recovery tasks) and grades the returned source.

## Loop

1. Build a system prompt describing the probe, the interface, and the tools.
2. Send a user prompt containing the task brief, interface header and examples.
3. Loop: read assistant output; execute any tool calls; append the results;
   repeat until `submit_solution` or the step budget.
4. Return the submitted source as `{candidate_source: text}` plus a ledger.

The workspace path is the only path the tools may touch. Every file access is
resolved and rejected if it escapes the workspace, because a protected task's
ground truth sits outside it.

## Tools exposed to the model

| Tool | Arguments | Notes |
|---|---|---|
| `list_files` | — | workspace-relative names only |
| `read_file` | `path` | UTF-8 text, size-capped, binary rejected |
| `run_probe` | `input` or `input_hex` | runs the workspace `probe` shim |
| `submit_solution` | `source` | final C++ file; ends the attempt |

For binary-recovery tasks the workspace `probe` is the **shim** described in
[`tools/aegis-bench/README.md`](../tools/aegis-bench/README.md): the harness
broker counts every query. An adapter that shells out to the artifact cache
instead would produce uncounted queries and is not a valid reference.
`submit_solution` is the only accepted delivery path; prose extraction is a
fallback and must be recorded in the ledger (see below).

## Parameters that must be recorded

Every published row must state:

- endpoint kind and base URL class (relay or first-party API);
- model id exactly as returned by `/v1/models`;
- whether thinking/reasoning was enabled, and how (parameter name);
- `temperature`, `max_tokens`, `max_steps`, adapter wall-clock timeout;
- reasoning-watchdog threshold, restart policy, wrap-up step;
- adapter source hash (the adapter reports it as `version`; the harness stores
  it as `adapter_version` in every row);
- date, harness commit, task content hash, repetition index.

Token and tool-call figures are self-reported by the adapter. Oracle queries are
counted by the harness. Reports label the two separately and never mix them.

## OpenAI-compatible endpoint notes

These were measured while building the reference adapter; they are properties of
the relays, not recommendations:

- **Streaming is mandatory** for long thinking responses behind Cloudflare-like
  proxies: a non-streaming completion can exceed the 120 s proxy read timeout
  (HTTP 524). SSE deltas keep the connection alive.
- Some deployments reject requests unless the previous assistant turn's
  `reasoning_content` is passed back verbatim (HTTP 400). The reference adapter
  accumulates and replays it. This inflates prompt tokens on every turn and must
  be reported with the cost.
- Thinking-budget parameters are not universally honoured; a parameter that is
  accepted is not necessarily applied. Verify by measuring `reasoning_tokens`,
  not by the absence of an error.
- `tool_choice: "required"` is not honoured by every relay. Do not rely on it to
  force tool use; use a wrap-up step and a step budget instead.

## Recovery policy (must be identical across profiles)

Reasoning length is bimodal for thinking models. The reference adapter:

- aborts a stream whose private reasoning exceeds a threshold without producing
  content or a tool call (`aborted_calls`, cost estimated and labelled);
- appends a short "act now" instruction after an unproductive reply;
- starts a fresh conversation after N consecutive unproductive replies;
- sends a wrap-up instruction at `max_steps - 4`.

Ledger fields: `tokens` (measured + estimated), `prompt_tokens`,
`completion_tokens`, `tokens_source`, `aborted_calls`,
`aborted_reasoning_chars`, `aborted_tokens_estimate`, `truncations`,
`restarts`, `tool_calls`, `llm_calls`, `stop_reason`, `model`, `max_tokens`,
`max_steps`, `temperature`, `thinking`.

A change to any of these changes the agent, so results from before and after the
change are not comparable at the profile level; rerun both cells.

## Reproduction checklist

1. Check out the commit named by the report.
2. Build the plugin in the pinned container and run `ctest`.
3. Obtain an equivalent adapter (the report names its source hash and the exact
   parameters above) and point it at an endpoint serving the same model id.
4. Run with the report's task ids, profiles, repetitions, step and token budgets.
5. Compare pass rates and oracle-query distributions; token figures also depend
   on how much reasoning the provider replays, which is why the adapter hash and
   endpoint kind are recorded.

A model result is only a claim once it has N >= 5 repetitions per cell, the
matrix in [`benchmark-protocol.md`](benchmark-protocol.md) is covered, and the
report is in the claims ledger. A pilot is a pilot.
