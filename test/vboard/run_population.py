# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""Draws N simulated chips from docs/VARIATION_MODEL.md, runs
bringup/binner_bringup.py against each one through the virtual demo board
(test/vboard/), and collects binner_<chip>.csv + truth_<chip>.json.

Run from WSL:
    source ~/tools/binner_env.sh
    python3 test/vboard/run_population.py --n 20 --seed 20260929 \
        --out ../../data/vboard/pop20_seed20260929 --jobs 4

Each chip gets its own `make` invocation (own SIM_BUILD directory, own
truth_<chip>.json, own env vars) so chips can run as separate OS processes
in parallel -- ProcessPoolExecutor, capped by --jobs. This machine (12
cores / 7.6GB RAM, WSL2) does NOT give 12 Icarus/cocotb processes real
headroom in practice: a single reduced-effort chip alone takes ~1150s real
time, but under 4-way concurrency that grew to ~2400-2660s per chip
(~45-48% parallel efficiency measured directly, not projected) -- --jobs
defaults to 4 for that reason, not the machine's nominal core count. See
bringup/README.md's "Measured runtimes" section for the full numbers and
for the real bug this uncovered in this script's original timeout handling
(a killed job's orphaned grandchild process used to keep running
unsupervised, silently doubling concurrent load for the next wave of jobs).
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import variation  # noqa: E402


def _plusargs_str(plusargs):
    return " ".join(plusargs)


def run_one_chip(args):
    (chip_label, seed, out_dir, reduced, vboard_dir, timeout_s) = args
    t0 = time.time()
    truth, plusargs = variation.draw_chip(seed)
    truth["chip_id"] = chip_label
    os.makedirs(out_dir, exist_ok=True)
    truth_path = os.path.join(out_dir, "truth_%s.json" % chip_label)
    with open(truth_path, "w") as f:
        json.dump(truth, f, indent=1)

    sim_build = os.path.join("sim_build", chip_label)
    env = dict(os.environ)
    env["BINNER_CHIP_ID"] = chip_label
    env["BINNER_OUT_DIR"] = os.path.abspath(out_dir)
    env["BINNER_TRUTH_JSON"] = os.path.abspath(truth_path)
    env["BINNER_REDUCED"] = "1" if reduced else "0"

    # SIM_BUILD and COCOTB_RESULTS_FILE both must be per-chip: every chip's
    # `make` runs concurrently from this *same* test/vboard directory (see
    # test/vboard/tb.v's comment on why no waveform is dumped there either),
    # and cocotb's results.xml defaults to a bare "results.xml" in the CWD.
    cmd = ["make", "-C", vboard_dir, "SIM_BUILD=%s" % sim_build,
           "COCOTB_RESULTS_FILE=%s/results.xml" % sim_build,
           "PLUSARGS=%s" % _plusargs_str(plusargs)]
    log_path = os.path.join(out_dir, "sim_%s.log" % chip_label)
    ok = True
    err = ""
    # Run `make` in its own process group (os.setsid) so a timeout can kill
    # the WHOLE tree -- make, and everything it forked (iverilog, then vvp
    # running the actual cocotb/bring-up simulation) -- not just the `make`
    # PID itself. Observed directly in this environment: a plain
    # subprocess.run(..., timeout=...)'s default kill() only reaches the
    # immediate child; `make`'s own children survive as orphans and keep
    # running to completion, unsupervised, for many more minutes of real
    # wall time. That is not just a stale-status cosmetic bug -- the next
    # wave of jobs then starts (this worker slot looks "free" the moment
    # subprocess.run() raises) while the orphaned previous job is still
    # actually consuming a full CPU core and its share of memory, so the
    # true concurrent load silently exceeds --jobs and can cascade into
    # otherwise-healthy jobs crashing under the extra contention.
    try:
        with open(log_path, "w") as logf:
            proc = subprocess.Popen(cmd, env=env, stdout=logf,
                                     stderr=subprocess.STDOUT,
                                     preexec_fn=os.setsid)
            try:
                rc = proc.wait(timeout=timeout_s)
                if rc != 0:
                    ok = False
                    err = "exit %s (see %s)" % (rc, log_path)
            except subprocess.TimeoutExpired:
                ok = False
                err = "timeout after %ds (see %s)" % (timeout_s, log_path)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    proc.wait(timeout=15)
                except Exception:
                    pass
    except OSError as e:
        ok = False
        err = "subprocess error: %s (see %s)" % (e, log_path)

    csv_path = os.path.join(out_dir, "binner_%s.csv" % chip_label)
    ok = ok and os.path.isfile(csv_path)
    return {
        "chip_id": chip_label, "ok": ok, "err": err,
        "elapsed_s": time.time() - t0, "csv": csv_path if ok else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    # Measured directly on this machine (12 cores / 7.6GB RAM, WSL2), not
    # guessed: a single reduced-effort chip alone takes ~1150s real time
    # (cocotb bridge/resume per-call overhead dominates, see
    # bringup/README.md); under 4-way concurrency that grew to ~2400-2660s
    # per chip (~45-48% parallel efficiency, not the naive 4x) -- this VM's
    # "12 cores" clearly do not give 12 independent Icarus/cocotb processes
    # real headroom. 4 was the largest concurrency actually exercised
    # end-to-end; --jobs defaults there rather than the previously-untested
    # 8. --timeout's old default (1800s) was tight enough to fire under
    # ordinary 4-way contention -- before the os.setsid/killpg fix above,
    # that produced not just a false FAIL report but genuine resource
    # pile-up (the "freed" slot immediately took a new job while the
    # orphaned old one kept running), which cascaded into unrelated jobs
    # crashing. 3600s gives real margin now that a timeout actually cleans
    # up its whole process tree.
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--reduced", action="store_true", default=True)
    ap.add_argument("--full-effort", dest="reduced", action="store_false")
    ap.add_argument("--timeout", type=int, default=3600,
                     help="per-chip wall-clock timeout, seconds")
    args = ap.parse_args()

    out = args.out or os.path.join(_HERE, "..", "..", "data", "vboard",
                                    "pop%d_seed%d" % (args.n, args.seed))
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)

    jobs = []
    for i in range(args.n):
        chip_label = "sim%02d" % i
        chip_seed = args.seed * 100000 + i
        jobs.append((chip_label, chip_seed, out, args.reduced, _HERE, args.timeout))

    print("population run: N=%d seed=%d reduced=%s jobs=%d out=%s" %
          (args.n, args.seed, args.reduced, args.jobs, out))
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(run_one_chip, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            status = "OK" if r["ok"] else ("FAIL: %s" % r["err"])
            print("  %-8s %6.1fs  %s" % (r["chip_id"], r["elapsed_s"], status))

    elapsed = time.time() - t0
    n_ok = sum(1 for r in results if r["ok"])
    print("done: %d/%d chips OK in %.1fs (%.1f min), avg %.1fs/chip" %
          (n_ok, len(results), elapsed, elapsed / 60.0,
           elapsed / max(1, len(results))))

    summary_path = os.path.join(out, "run_summary.json")
    with open(summary_path, "w") as f:
        json.dump({"n": args.n, "seed": args.seed, "reduced": args.reduced,
                    "jobs": args.jobs, "elapsed_s": elapsed,
                    "n_ok": n_ok, "results": results}, f, indent=1)
    print("summary: %s" % summary_path)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
