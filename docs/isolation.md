# Isolation and tool accounting

Status: the loopback tool broker, adapter subprocess, Linux Landlock
filesystem/TCP-port boundary, and seccomp non-stream-socket block are
implemented. A non-Linux or Landlock-disabled process is only a process
boundary. Full network-namespace isolation remains open.

## What is implemented

| Boundary | Implemented behaviour |
|---|---|
| Agent workspace | only files named by `visible` are copied |
| Ground truth | stays outside the workspace; task-load and workspace tests assert it |
| Candidate sources | bare filenames only; path traversal is rejected |
| Candidate include policy | absolute/parent includes and grader paths are rejected |
| Compile/run scratch | private directory, minimal environment, timeout, rlimits, output cap |
| Oracle access | harness broker counts and optionally caps queries |
| Token traffic | optional loopback proxy measures provider `usage` |
| Campaign persistence | atomic reports, checkpoint, resume, audit |
| Task tool contract | schema v2 `tool_policy` records the declared tool set |
| Tool broker | loopback policy checks, counters, byte caps and call cap when the adapter uses it |
| Adapter process | optional fresh child process with a workspace-only TaskView and no repository task root |
| Landlock worker | Linux filesystem allowlist and TCP connect rules for broker/meter ports |
| Seccomp worker | deny UDP/raw/RDM/SEQPACKET IP socket creation |

These controls stop accidental leakage and several replay tricks. They do not
stop a malicious adapter from walking the host filesystem, reading the
artifact cache, opening a direct socket, or executing subprocesses. Adapters
are therefore trusted code until the worker boundary below exists.

## Target architecture

```text
                   control plane (trusted)
  experiment manifest -> campaign planner -> cell supervisor
                                                |
                 +------------------------------+-------------------+
                 |                                                  |
          adapter worker (untrusted)                       tool broker (trusted)
          - fresh process implemented                      - workspace-relative FS
          - container/namespace next                       - counters + limits
          - workspace mounted rw                             - run_probe
          - adapter code mounted ro                           - disassemble
          - egress only to meter proxy                        - denial log
                 |                                                  |
                 +------------------ JSON result -------------------+
                                                |
                                         grader worker (trusted)
                                         - candidate text only
                                         - no adapter process
```

The control plane owns the experiment and never executes model output. The
adapter worker sees only its workspace, an adapter bundle and the tool broker.
The grader receives candidate text and hidden grading material in a separate
process, so a compromised adapter cannot observe the grader's file view.

## Worker boundary

The implemented first stage is one fresh subprocess per cell, optionally
sandboxed by Landlock. The stronger container boundary remains:

1. Create a fresh workspace with only the declared visible files.
2. Start a disposable container or namespace with a read-only adapter mount.
3. Mount the workspace read-write and nothing else from the repository.
4. Mount no task root, ground truth, hidden cases, policy source, artifact
   cache or prior workspace.
5. Give the worker no host PID namespace, no host network and no inherited
   credentials beyond the per-run meter URL/token.
6. Stop and delete the worker after the result, timeout or crash.

The harness already starts one oracle broker and one meter per run. Those
become network services scoped to the worker's lifecycle.

The subprocess path uses `TaskView.path()` to hide task-root paths and keeps
the broker/meter endpoints in the child environment. On Linux with Landlock,
the worker installs a filesystem allowlist and permits TCP connects only to the
broker/meter ports. A narrow seccomp policy also denies UDP/raw/RDM/SEQPACKET
IP socket creation. The tests verify that repo reads, unapproved TCP ports, and
UDP sockets are denied. Same-port IP targeting and non-Linux hosts remain
outside this boundary.

## Tool broker

The implemented first stage exports a loopback broker and a client helper. The
reference adapter prefers it over direct workspace access. The broker
validates each request against the task's schema-v2 `tool_policy`:

| Tool | Broker behaviour | Counted evidence |
|---|---|---|
| `list_files` | list workspace-relative entries only | calls, entries returned |
| `read_file` | resolve inside workspace, text/size/binary checks | calls, bytes, denials |
| `run_probe` | execute only the broker-held or workspace artifact | calls, input/output bytes, exit code, oracle count |
| `disassemble` | invoke a pinned tool over the artifact, cap output | calls, bytes, lines, denial reason |
| `submit_solution` | validate names/size/policy and return source text | calls, accepted/rejected, byte count |

Every broker call gets a monotonically increasing sequence number, start/end
time and status. A run row adds:

```json
{
  "tools": {
    "calls": 31,
    "calls_by_tool": {"run_probe": 12, "disassemble": 18, "submit_solution": 1},
    "denied": 2,
    "denials": [{"tool": "read_file", "reason": "escapes workspace"}],
    "bytes_read": 48120,
    "bytes_returned": 221904
  }
}
```

The row now distinguishes broker-measured calls (`tools.*`) from the adapter's
own ledger. `budgets.max_tool_calls` is enforced by broker refusal for mediated
calls. The remaining gap is enforcement against direct filesystem/subprocess
access: under the worker design the broker is the only available path.

## Network and metering

The worker may reach only the harness meter proxy. The proxy forwards the
approved model endpoint and records provider `usage`; a direct endpoint
connection must fail at the worker's network policy.

This closes the current meter gap: today an adapter can bypass the proxy while
still producing a plausible self-report. Under isolation:

- direct egress is denied by the worker's network namespace;
- the broker and meter are per-cell ports with no cross-cell reuse;
- provider retries remain inside the measured path;
- abandoned calls retain the current close-on-client-disconnect rule;
- the metered total stays a floor when no usage arrives, and is labelled as
  such rather than replaced with a character estimate.

Token metering remains accounting, not sandboxing. Isolation supplies the
network enforcement; the meter supplies the provider-attested number. The tool
broker follows the same rule: it is authoritative only for calls that reach it.

## Isolation acceptance tests

A release must fail if any of these controls is missing:

- worker cannot open a file above its workspace mount;
- a symlink in the workspace cannot resolve outside the mount;
- worker cannot see the task root, artifact cache, hidden cases or `/proc`
  entries for trusted processes;
- direct DNS/HTTP egress fails; only the meter origin is reachable;
- executing the cached probe directly is impossible because the cache is not
  mounted, and `run_probe` requests are attributed to the broker;
- oversized read/disassembly output is truncated and counted, not buffered;
- `submit_solution` cannot smuggle extra paths or an oversized source;
- killing the worker leaves no child process or listening proxy;
- grader input contains candidate text only and no worker filesystem handle;
- a second cell gets a new workspace, meter, oracle broker and tool counters.

## Publishability gate

A campaign can be used as a **measurement** when reports are metered and
auditable. A campaign can support a **protection-effect claim** only when
`require_sandbox: true` rows pass audit and the remaining full-egress
acceptance items are closed:

- token results may be cited only with the current meter caveat;
- broker tool counts describe mediated calls, while `tools.requests: 0` means
  the adapter bypassed the broker;
- oracle access is counted only because the workspace holds the shim;
- binary access does not count local executions;
- TCP is port-restricted rather than IP-restricted, and this is not a network
  namespace;
- no report may imply that the adapter or grader is fully host-isolated.
