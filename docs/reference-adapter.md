# Reference adapter protocol

Adapters live **outside** this repository. That is deliberate: an adapter imports
a network client and reads an API key, and neither belongs in the tree or in CI.
This document is the contract a published result must satisfy, so someone else
can rebuild an equivalent adapter and check the numbers.

The harness itself is vendor-neutral: it hands `solve(task, workspace)` a
workspace containing only the task's visible files, plus for binary-recovery
tasks either the counted oracle **shim** (`--access oracle`) or the stripped
**probe binary** (`--access binary`). The reference adapter must support both;
a tool it offers in one mode and not the other makes the two runs
incomparable.

## Loop

1. Build a system prompt describing the probe, the interface, and the tools.
2. Send a user prompt containing the task brief, interface header and examples.
3. Loop: read assistant output; execute any tool calls; append the results;
   repeat until `submit_solution` or the step budget.
4. Return the submitted source as `{candidate_source: text}` plus a ledger.

The workspace path is the only path the tools may touch. Every file access is
resolved and rejected if it escapes the workspace, because a protected task's
ground truth sits outside it.

Task schema v2 declares the same tool surface in `tool_policy.allowed_tools`
and records it in every row as `task_protocol.tool_policy`. Runner exports a
loopback tool broker as `AEGIS_TOOL_BROKER_URL` and
`AEGIS_TOOL_BROKER_TOKEN`; the reference adapter prefers it over local tool
implementations. The broker enforces the policy and call cap for mediated
calls and writes measured counters to the row's `tools` block. An adapter can
still bypass it while it remains in-process, so a published result must not
describe the current adapter process as sandboxed.

## Tools exposed to the model

| Tool | Arguments | Notes |
|---|---|---|
| `list_files` | — | workspace-relative names only |
| `read_file` | `path` | UTF-8 text, size-capped, binary rejected |
| `run_probe` | `input` or `input_hex` | broker executes its verified private artifact or queries the counted oracle; output capped |
| `disassemble` | `symbol` or `offset`+`length` | `llvm-objdump -d`/`objdump -d` over the broker's private artifact snapshot; output capped. Offered only under `binary` access |
| `submit_solution` | `source` | final C++ file; ends the attempt |

Under `oracle` access the workspace `probe` is the **shim** described in
[`tools/aegis-bench/README.md`](../tools/aegis-bench/README.md) and the harness
broker counts every query. An adapter that shells out to the artifact cache
instead would produce uncounted queries and is not a valid reference.

Under `binary` access the workspace `probe` is the stripped artifact itself:
brokered `run_probe` and `disassemble` use a verified private copy of the same
artifact. Replacing the workspace copy cannot change the broker's target.
Direct local execution remains possible in the worker, so oracle queries are
**not counted** and a protection transform can change what the agent has to
work through. A protection comparison must state which access mode it used;
an `oracle`-access comparison cannot show an effect at all (the shim is
identical in every profile), so it is a black-box synthesis result, not a
protection result.

The reference static tool is a **linear disassembler**, not a decompiler. That
is a deliberate, stated limitation: the measured adversary is weaker than a C2
attacker holding Ghidra/IDA and a scripting layer. A `binary`-access result
therefore bounds the protection cost from below against such an attacker, and
anything built on it must say so.

`submit_solution` is the only accepted delivery path; prose extraction is a
fallback and must be recorded in the ledger (see below).

## Parameters that must be recorded

Every published row must state:

- endpoint kind and base URL class (relay or first-party API);
- model id exactly as returned by `/v1/models`;
- **access mode** (`oracle` or `binary`) and, for binary, which static tools
  were offered;
- whether thinking/reasoning was enabled, and how (parameter name);
- `temperature`, `max_tokens`, `max_steps`, adapter wall-clock timeout;
- reasoning-watchdog threshold, restart policy, wrap-up step, and whether a
  final-answer turn is used;
- adapter source hash (the adapter reports it as `version`; the harness stores
  it as `adapter_version` in every row);
- complete effective non-secret constructor options in `agent_config`, including
  `config_sha256` for the reference adapter;
- date, harness commit, task content hash, repetition index.

Token figures are self-reported by the adapter unless the run went through the
harness metering proxy. Broker tool calls are measured by the harness;
`ledger.tool_calls` remains the adapter's self-report. Oracle queries in oracle
access are counted by the harness. Reports label the kinds separately and
never mix them.

Adapters used in a campaign must expose a stable non-empty `version` (normally
a source hash). The campaign preflights that value and every run row records
it as `adapter_version`. A fresh adapter instance is created for each cell, so
counters, notes, cached listings and conversation state cannot cross
repetitions.

## Tool broker: `AEGIS_TOOL_BROKER_URL`

When enabled (the default), the runner starts a loopback JSON broker with a
per-cell random token. Adapter tool dispatch should call
`aegis_bench.toolbroker.call_tool(name, args)`. The broker:

- validates `name` against `task_protocol.tool_policy.allowed_tools`;
- confines reads to the workspace and rejects escaping symlinks;
- caps tool calls with `budgets.max_tool_calls`;
- executes `run_probe` and, under `binary` access, `disassemble`;
- applies the candidate-source policy to `submit_solution`;
- records calls by tool, denials, failures and byte counts.

The row also keeps `ledger.tool_calls`; `tools.adapter_exceeds_broker` becomes
true if the adapter claims more calls than the harness observed. A campaign
can set `require_broker_tools: true`, which makes audit fail when the adapter
did not use the broker.

With `adapter_isolation: "process"`, the harness imports the adapter in a
fresh child process and passes a `TaskView` whose `path()` is restricted to
workspace-visible files. The adapter receives the broker/meter environment but
not the repository `Task` object. With `require_sandbox: true` on Linux, a
Landlock ruleset runs before adapter code and allows only runtime/workspace
files plus TCP connections to the broker/meter ports. A seccomp rule denies
UDP/raw/RDM/SEQPACKET IP socket creation. With
`require_network_namespace: true`, the worker enters a private loopback-only
network namespace. Broker and meter are reached through per-run Unix sockets
bridged to loopback; direct host connections have no route. Adapter-side
diagnostic saves under `LLM_SAVE_DIR` are redirected to the per-cell worker
transport directory.

With `adapter_isolation: "container"`, the same worker and adapter contract run
inside a disposable non-root container. The adapter directory must be present
in `PYTHONPATH`; it is mounted read-only at a fixed path inside the container.
The workspace is read-write, the root filesystem is read-only, and network
access is disabled. A container adapter must therefore be self-contained in
the configured image and explicit read-only mounts.

Campaign agents supply JSON `options` to the adapter constructor. An adapter
can implement the optional `effective_options()` protocol to return its complete
non-secret constructor options after resolving environment defaults. The harness
records that object as `agent_config` and uses it to recreate the adapter in both
process and container workers. Adapters without this protocol retain their
caller-supplied options.

The reference `OpenAICompatAgent` implements this protocol. Its options pin
`base_url`, `model`, `max_steps`, `max_tokens`, `hard_tokens`, `call_timeout`,
`temperature`, `restart_after`, `reasoning_limit`, `retries` and `config_sha256`.
The source `version` identifies code; the configuration fingerprint identifies
effective parameters. API keys are excluded from both the options and the
configuration fingerprint. Base URLs with credentials, query parameters or
fragments are rejected. Broker/meter transport addresses are resolved per run.

**Model-only options are insufficient for the current reference adapter.**
Campaign preflight rejects incomplete options rather than silently mixing
environment-dependent defaults into a pinned experiment. The out-of-tree pilot
wrapper generates complete options automatically. It also pins the outer adapter
timeout and validated meter upstream in manifest `notes`, which participate in
the manifest hash.

For a hand-written campaign, generate a new manifest from the example using the
intended model endpoint and parameter environment. From the repository root,
with the updated adapter on `PYTHONPATH` and `LLM_API_KEY` available:

```bash
export PYTHONPATH="$PWD/tools/aegis-bench:/path/to/adapters"
python3 - <<'PY'
import json
from pathlib import Path
from openai_adapter import OpenAICompatAgent

root = Path.cwd().resolve()
manifest = json.loads(
    (root / "experiments/protection-pilot.example.json").read_text())
for entry in manifest["agents"]:
    agent = OpenAICompatAgent(model=entry["options"]["model"])
    entry.update(
        id=agent.name,
        adapter="openai_adapter:OpenAICompatAgent",
        expected_version=agent.version,
        options=agent.effective_options(),
    )
manifest["tasks_root"] = str(root / "benchmarks/tasks-public")
manifest["out"] = str(root / "bench-out/protection-pilot")
manifest["notes"] = "Generated complete reference-adapter configuration."
target = root / "bench-out/protection-pilot.config.json"
target.parent.mkdir(parents=True, exist_ok=True)
with target.open("x", encoding="utf-8", newline="\n") as stream:
    stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(target)
PY
```

This constructs adapters without calling the model or printing credentials. It
generates source versions and configuration hashes from the installed adapter;
do not hand-edit those hashes. The example's placeholder options are replaced
in full. The generated manifest uses absolute paths so moving it out of
`experiments/` does not change the task/output locations.

Run the generated manifest with the same upstream and timeout settings throughout
the experiment. The direct CLI keeps these execution settings as CLI arguments;
use the pilot wrapper when they also need to be pinned in the manifest. A changed
manifest cannot resume an existing campaign. To continue an interrupted run,
reuse its original complete options; worker environment defaults will not
override them. Historical reports and their original manifests remain frozen.

## Metering: `AEGIS_METER_BASE_URL`

When the harness runs with `--meter-upstream`, it starts a loopback proxy in
front of the relay and exports `AEGIS_METER_BASE_URL` for the duration of the
run. **An adapter that makes model calls must prefer that variable over its own
endpoint configuration**, read at `prepare`/`solve` time rather than at import
time (the variable is per run). The proxy forwards requests unchanged, adds
`stream_options.include_usage` to streaming requests so the provider reports
token usage, and records those totals in the row's `metering` block.

What this changes for the adapter author: nothing about the agent, and
everything about the evidence. Tokens stop being the adapter's arithmetic and
become the provider's own report, captured by the harness. An adapter that
ignores the variable still runs; its rows simply stay labelled self-reported,
and `metering.requests` is `0` for those runs — visible, not silently wrong.

The proxy is not a sandbox: reaching the relay directly bypasses it. It also
means the adapter must keep its own accounting, because
`metering.adapter_exceeds_metered` compares the two and a large gap is
evidence that traffic left the proxy.

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
- sends a wrap-up instruction at `max_steps - 4`;
- makes **one tool-free final turn** when the budget expires without a
  submission, so the run is graded instead of discarded. On relays that accept
  it, thinking is disabled for that turn: with thinking on, a model can spend
  the entire output budget reasoning and return no source at all. A run that
  never submits has no grade and no cost, which is why this turn exists and why
  its presence must be declared.

Ledger fields: `tokens` (measured + estimated), `prompt_tokens`,
`completion_tokens`, `tokens_source`, `aborted_calls`,
`aborted_reasoning_chars`, `aborted_tokens_estimate`, `truncations`,
`restarts`, `tool_calls`, `llm_calls`, `stop_reason`, `model`, `max_tokens`,
`max_steps`, `temperature`, `thinking`, `tool_broker_calls`,
`tool_broker_used`, `hard_tokens`, `retries`, `config_sha256`.

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

For a multi-cell run, generate complete options as above, then run from the
repository root. Substitute the actual upstream used when generating the options:

```bash
PYTHONPATH="$PWD/tools/aegis-bench:/path/to/adapters" \
python3 -m aegis_bench campaign \
  --config bench-out/protection-pilot.config.json --plugin build/lib/AegisPass.so \
  --meter-upstream https://relay.example/v1
PYTHONPATH="$PWD/tools/aegis-bench:/path/to/adapters" \
python3 -m aegis_bench audit bench-out/protection-pilot \
  --experiment bench-out/protection-pilot.config.json --strict
```

The campaign manifest, resume and audit contract are in
[`campaigns.md`](campaigns.md).

A model result is only a claim once it has N >= 5 repetitions per cell, the
matrix in [`benchmark-protocol.md`](benchmark-protocol.md) is covered, and the
report is in the claims ledger. A pilot is a pilot.
