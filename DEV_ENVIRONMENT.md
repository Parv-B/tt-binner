# Development environment notes

This repo is developed on a Windows host with a WSL Ubuntu sidecar for the actual
EDA toolchain. Every agent/session working on this repo hits the same handful of
environment gotchas; read this first.

## Where things run
- **Simulation (iverilog/verilator/yosys/cocotb)**: WSL Ubuntu only. Windows has none
  of these tools installed.
- **GitHub API / CI orchestration** (`tools/ci.py`): Windows host Python (via Git Bash),
  using the token from Git Credential Manager. Works fine from WSL too if needed.
- **Everything else** (editing files, git): either side works; this repo was mostly
  edited from the Windows host with Git Bash as the shell.

## WSL toolchain
One-time setup already done in `~/tools/` and `~/pdk/` inside WSL (not part of this
repo — do this again on a fresh machine):
- `~/tools/oss-cad-suite/` — OSS CAD Suite (iverilog 14, verilator, yosys), with a
  bundled Python 3.11 that has `cocotb==2.1.0`, `pytest==8.4.2`, numpy/scipy/pandas
  installed into it (installing cocotb into a *different* Python breaks `vvp`, which
  hard-codes its own bundled interpreter via `PYTHONHOME`).
- `~/pdk/gf180mcuD/` — the GF180MCU PDK at the exact ciel release LibreLane 3.0.14
  pins (`54435919abffb937387ec956209f9cf5fd2dfbee`), extracted from
  `fossi-foundation/ciel-releases`.
- `~/tools/binner_env.sh` — sources the OSS CAD Suite environment and exports
  `PDK_ROOT=~/pdk`, `PDK=gf180mcuD`.

Run any simulation like:
```bash
wsl.exe -e bash -lc 'source ~/tools/binner_env.sh; cd "/mnt/c/Users/.../tt-binner/test" && make clean && make'
```
Map a Windows path `C:\X\Y` to `/mnt/c/X/Y` — WSL cannot see Windows paths any other way.

## GitHub API calls from Git Bash
Git Bash's MSYS layer rewrites arguments that look like absolute Unix paths
(`/repos/...`) before they reach the program — `/repos/foo/bar` can silently become
`C:/Program Files/Git/repos/foo/bar`. Always prefix API calls with
`MSYS_NO_PATHCONV=1`:
```bash
MSYS_NO_PATHCONV=1 python tools/ci.py status --branch feat/must
```
`tools/ci.py` never takes a token on the command line or in an env var you set by
hand — it pulls one from Git Credential Manager in-process (`git credential fill`)
and never prints or logs it. Don't paste tokens into shell history either.

## Encoding
Every `open()` call in throwaway/glue Python (inline heredocs, one-off scripts) MUST
pass `encoding="utf-8"` explicitly, on both read and write, and `newline="\n"` on
write. The Windows Python default encoding is the system code page (cp1252 on this
machine), not UTF-8 — mixing that default with files that already contain non-ASCII
characters (em dashes, °, ±, µ) silently produces mixed-encoding files that fail to
parse later (this happened once to `docs/SPEC.md`; recovered by decoding line-by-line
with a UTF-8-first / cp1252-fallback pass — see git history around commit 908c9e1 if
you need the recipe again). `tools/ci.py` also reconfigures `sys.stdout` to UTF-8
with `errors="replace"` for the same reason (GitHub Actions logs contain box-drawing
characters that cp1252 can't encode).

Prefer plain ASCII in new docs/comments where a straight quote or hyphen reads just
as well — it sidesteps the whole problem.

## cocotb/vvp simulations are slow and don't parallelize well here
A single `test/vboard` bring-up run (cocotb bridge/resume against Icarus) takes on
the order of **20 minutes of real wall time** even in reduced-effort mode, for well
under 2 seconds of simulated time — the cost is per-pin-access bridge/thread-hop
overhead, not RTL complexity (see `bringup/README.md`'s "Measured runtimes" section
for the full breakdown). This machine reports 12 cores / 7.6GB RAM, but does **not**
give that many Icarus/cocotb processes real headroom: 4 concurrent chips measured
~45-48% parallel efficiency (each took 2400-2660s instead of the ~1150s solo figure),
not the naive 4x. Always launch any `make`/cocotb run backgrounded/detached and poll
its log rather than blocking on it — a blocking call risks exceeding whatever is
supervising it, and if a supervisory timeout then kills only the immediate `make`
process (not its whole process tree), the actual simulator is orphaned and keeps
running unsupervised, invisibly doubling load for whatever runs next. See
`test/vboard/run_population.py`'s `run_one_chip()` (`os.setsid` + `os.killpg()`) for
the pattern that avoids this.

## Git worktrees for subagents
`.claude/` is gitignored. Subagents spawned with `isolation: "worktree"` land under
`.claude/worktrees/agent-<id>/` as real git worktrees on their own branch. If you
need to resume one after it dies mid-task (rate limit, crash, etc.), the branch and
any uncommitted files are still there — `git status`/`git log` in that directory
before assuming the work is lost. To bring a stale worktree up to date with the
latest integration branch: `cd` into it, `git stash -u` (if there are uncommitted
files), `git merge feat/must`, `git stash pop`.
