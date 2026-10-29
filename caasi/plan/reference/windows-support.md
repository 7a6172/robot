# Windows support: findings and design (parked, not implemented)

Status: **research complete, code not written.** Nothing in this file is implemented. The goal is to
be able to pick this up cold, with the facts already established, without repeating the audit.

Date of findings: 2026-10-30, caasi 0.4.0.
Verified on: Linux dev machine + `swjtumover05` (Ubuntu 24.04, ROS 2 Jazzy). **No Windows machine was
available**, so every claim below about Windows is from reading the code and from documented Windows
behaviour — it needs one real Windows pass before anything is promised to users.

---

## 1. The question

caasi is built around NVIDIA Isaac, which runs on Linux. The developer's own view: no Windows support
for development, because the lab stack is Linux. But a Windows user should still be able to *work*:
write code locally, and have every build, launch and simulation happen on a Linux machine over SSH.

So the model is not "caasi on Windows" but **caasi as a thin client**: the editor is anywhere, the
work is on a target. That is already how caasi is used from the dev machine — the only difference is
that a Windows host cannot be the machine that runs things.

---

## 2. What was verified about the code

### 2.1 What a Windows host would be able to do today

These are plain SSH/HTTP work with no POSIX dependency, so they should already function:

| command | why it works |
| --- | --- |
| `caasi node enroll/check/list/refresh` | `ssh`/`scp` (OpenSSH ships with Windows 10+) |
| `caasi choose target/robot/project` | config file I/O |
| `caasi exec -- ...` | `ssh` to the target, command string built for the *target* shell |
| `caasi run start/logs/stop --target` | run state lives on the target; only `ssh` used from here |
| `caasi ros2 ...` (remote) | same |
| `caasi artifacts`/`logs` | remote reads |
| `caasi config`/`help`/`version` | pure Python |

### 2.2 What breaks, and where

Audited by grepping the source; file:line is from the 0.4.0 tree.

| blocker | location | consequence on Windows |
| --- | --- | --- |
| `rsync` | `core/deploy.py` (24 references), `core/artifacts.py` (3) | **`caasi deploy` fails outright.** This is the one blocker that matters: deploy is the Windows user's whole job |
| `bash -c` wrapper for local work | `core/runs.py`, `core/runtimes.py`, `core/execution.py`, `cli/shell_cmd.py` | local runs/builds impossible; no `bash` on Windows |
| `start_new_session=True` (POSIX-only kwarg) | `core/runs.py:404`, `core/viewers.py:72` | process spawning for local runs |
| `os.killpg` / `SIGKILL` | `core/runs.py:483,642,660` | stopping local runs; **already falls back** to `os.kill` and catches `OSError`, so this degrades rather than crashes |
| `fcntl` | `core/identity.py:342` | **already inside `try/except Exception`** — only loses interface addresses, harmless |
| `shlex.quote` on remote paths | everywhere remote | fine: quoting is for the *target's* POSIX shell, and the target is Linux |
| `tar` | not used today | available on Windows 10+ as `tar.exe` (bsdtar) — this is the way around `rsync` |
| Isaac Sim / Isaac Lab | `sim`/`lab`/`train` backends | Linux-only by NVIDIA; cannot be fixed here, must run on a GPU target |

`caasi` itself is pip-installable on Windows (`pipx` is cross-platform), and its Python dependencies
(`typer`, `rich`, `pyyaml`, …) are pure Python. Nothing in the audit suggested an import that fails at
startup on Windows.

---

## 3. Design that was worked out (not implemented)

Three modules' worth of change. Written down so the next pass can implement directly.

### 3.1 `core/host.py` — one place that answers "can this host do X"

```python
IS_POSIX = os.name == "posix"
local_execution_supported()   # False when there is no POSIX shell
session_kwargs()              # {'start_new_session': True} | {'creationflags': CREATE_NEW_PROCESS_GROUP}
local_unsupported(what)       # the sentence printed when local work is refused
```

The point of a single module is that **every** refusing command says the same thing, and names the
same two ways forward. Draft text:

> `'caasi run start bringup.yaml'` has to run on a Linux machine, and this is Windows. Nothing is
> wrong with your project — pick the machine that does the work: `caasi node list` shows what you
> have enrolled, `caasi choose target <name>` makes one the default, or add `-t <name>` to this
> command. To run caasi itself on this computer instead, use WSL2 (Ubuntu): everything works there
> unchanged.

Refusal sites: `cli/run_cmd.launch_experiment` (covers `run`, `sim`, `lab`, `train`, `benchmark`,
`dataset`, `platform`, `teleop` — they all funnel through it) and the local branch of
`core/build.py`. Both only refuse when the resolved target is **local**; naming a target makes them
work normally.

### 3.2 `core/transfer.py` — deploy without rsync

`tar` over the same SSH connection:

```
tar -C <project_root> -cf -  .            →  (stdin)  →  ssh <target> "mkdir -p <dest> && tar -C <dest> -xf -"
```

Two processes joined by a pipe; the destination is created first so a fresh robot works. Windows 10+
has both `tar.exe` and `ssh`.

Two losses, which must be **said out loud** rather than hidden:

* **deletions are not propagated** — rsync's `--delete` has no equivalent here, so a file deleted
  locally stays on the target (the existing `.caasi-deployment.json` revision marker still protects
  caasi's own bookkeeping from being eaten);
* **no itemised change list** — the count reported is what was *sent*, not what *differed*.

Warning text drafted for the deploy record:

> rsync is not available on this host, so the project was copied with tar over ssh: files arrive, but
> files deleted here are not deleted on the target and no change list is produced. Install rsync, or
> run deploy from WSL2/Linux, for incremental deploys.

### 3.3 Process-session flags

`runs.py`/`viewers.py` pass `start_new_session=True`. Replace with
`**host.session_kwargs()` so Windows gets `creationflags=CREATE_NEW_PROCESS_GROUP` instead.

---

## 4. Traps found while drafting

* **`DeploymentRecord` field names are not what they look like.** The record uses `file_count`,
  `total_bytes`, `transferred_bytes`, `changed_files`, `warnings`, `errors`, `duration_seconds` —
  a first attempt at the tar branch invented `files_deployed` and would have raised `TypeError` only
  on Windows (never on the Linux dev machine, which has rsync). Anyone implementing this must check
  the dataclass, not the record's `to_dict()` output.
* **The rsync path also carries the `--delete`-vs-revision-marker logic** (`deploy.py:60`). Any tar
  transport must not delete, and should keep the same marker semantics.
* **Do not "fix" the remote quoting for Windows.** `shlex.quote` produces POSIX quoting, but it is
  applied to commands executed *on the target*, which is Linux. Changing it would break Linux
  targets.
* **`caasi build` on a Windows host must go to a target**, and the target build path
  (`bash -c` over ssh, `cd` + `source` + `colcon`) is already POSIX and unaffected.
* WSL2 sidesteps every single blocker above. If effort is short, document WSL2 and stop; the
  thin-client work is only worth it if native Windows is a product requirement.

---

## 5. Open questions for the decision

1. Is "native Windows, targets do the work" a requirement, or is "install WSL2" acceptable? WSL2
   costs the user one install and caasi zero code; native support costs the work in §3 plus a test
   matrix that cannot be run on the current hardware.
2. Should local **simulation** be refused on Windows, or offered as "run it on a GPU target"
   automatically when a `gpu` role is chosen? Today `sim`/`lab`/`train` already default to the local
   machine when no gpu target is chosen, which on Windows would hit the refusal in §3.1 — good
   enough, but the message should probably mention the gpu role explicitly.
3. Does `caasi deploy` from Windows need `--delete` parity (a tar-based diff), or is "copies, never
   deletes" acceptable as the documented Windows behaviour?

---

## 6. Test plan for a real Windows pass

Cannot be done on the current machines. When one is available:

1. `pipx install caasi` on Windows 11 (PowerShell, then also `cmd`).
2. `caasi node enroll swjtumover05 --host <ip> --user swjtumover` → expect success; check the managed
   `known_hosts` file is written and that host-key verification is not bypassed.
3. `caasi exec -- uptime` → success; confirm the command is built for the target, not the host.
4. `caasi run start experiments/bringup.yaml -t swjtumover05` → success; `caasi logs` shows both
   streams.
5. `caasi deploy` with no rsync installed → expect the tar transport, the warning, and `VERIFIED`.
6. `caasi deploy` then delete a file locally and deploy again → confirm the file **remains** on the
   target, and that the warning said so.
7. `caasi run start experiments/bringup.yaml` with no `-t` and no chosen target → expect the §3.1
   refusal text, not a traceback.
8. `caasi build` with no target → same refusal; with `-t swjtumover05` → builds on the robot.
9. Ctrl-C during `caasi logs -f` and during `caasi run stop` → no orphaned `ssh` processes
   (`Get-Process ssh`), since process-group semantics differ.
10. Paths with spaces and a non-ASCII username (`C:\Users\张伟`) through deploy and run.

---

## 7. Effort estimate

| piece | size | risk |
| --- | --- | --- |
| `core/host.py` + refusal sites | ~1 hour | low — pure Python, testable by faking `os.name`/`which` |
| `core/transfer.py` + deploy branch | ~2 hours | medium — pipe plumbing, and the record field mismatch in §4 |
| docs (a Windows page + notes) | ~1 hour | low |
| real Windows verification | unknown | **blocked**: no Windows machine |

Until a Windows machine exists, the honest user-facing position is: *caasi needs Linux or WSL2; from
Windows, use WSL2.* That is also what NVIDIA requires for Isaac Sim, so it is not a caasi-specific
limitation.
