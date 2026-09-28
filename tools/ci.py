#!/usr/bin/env python3
"""CI helper for tt-binner: watch workflow runs and download artifacts.

Token source (never printed, never written to disk):
  1. $GITHUB_TOKEN / $GH_TOKEN, else
  2. `git credential fill` for github.com (Git Credential Manager).

Usage:
  python tools/ci.py status [--sha SHA|--branch BR]      # one line per workflow run
  python tools/ci.py wait   [--sha SHA|--branch BR]      # block until all runs complete
  python tools/ci.py fetch  [--sha SHA|--branch BR] [--out DIR] [--name ART ...]
  python tools/ci.py jobs   RUN_ID                       # job/step conclusions
  python tools/ci.py log    JOB_ID [--tail N]            # job log tail
"""
import argparse
import io
import os
import subprocess
import sys
import time
import zipfile

import requests

REPO = os.environ.get("BINNER_REPO", "Parv-B/tt-binner")
API = "https://api.github.com"


def _token():
    for k in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, env=env)
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line[len("password="):]
    sys.exit("ci.py: no GitHub token available")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

S = requests.Session()
S.headers.update({"Authorization": "token " + _token(),
                  "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28"})


def get(path, **params):
    r = S.get(path if path.startswith("http") else API + path, params=params)
    r.raise_for_status()
    return r.json()


def head_sha(branch):
    return get(f"/repos/{REPO}/commits/{branch}")["sha"]


def runs_for(sha):
    return get(f"/repos/{REPO}/actions/runs", head_sha=sha, per_page=50)["workflow_runs"]


def resolve_sha(a):
    if a.sha:
        return a.sha
    return head_sha(a.branch or "main")


def cmd_status(a):
    sha = resolve_sha(a)
    runs = runs_for(sha)
    print(f"sha {sha[:10]}: {len(runs)} runs")
    for r in sorted(runs, key=lambda r: r["name"]):
        print(f"  {r['name']:<22} {r['status']:<11} {str(r['conclusion']):<10} id={r['id']}")
    return runs


def cmd_wait(a):
    sha = resolve_sha(a)
    t0 = time.time()
    while True:
        runs = runs_for(sha)
        pending = [r for r in runs if r["status"] != "completed"]
        if runs and not pending:
            break
        if time.time() - t0 > a.timeout:
            print("timeout waiting for runs")
            break
        time.sleep(30)
    a.sha = sha
    runs = cmd_status(a)
    bad = [r for r in runs if r["conclusion"] not in ("success", "skipped")]
    sys.exit(1 if bad else 0)


def cmd_jobs(a):
    for j in get(f"/repos/{REPO}/actions/runs/{a.run_id}/jobs")["jobs"]:
        print(f"{j['name']:<20} {j['conclusion']} id={j['id']}")
        for s in j.get("steps", []):
            if s["conclusion"] not in ("success", "skipped"):
                print(f"    step {s['number']}: {s['name']} -> {s['conclusion']}")


def cmd_log(a):
    r = S.get(f"{API}/repos/{REPO}/actions/jobs/{a.job_id}/logs")
    r.raise_for_status()
    lines = r.text.splitlines()
    for line in lines[-a.tail:]:
        print(line)


def cmd_fetch(a):
    sha = resolve_sha(a)
    out = a.out or os.path.join("ci_artifacts", sha[:10])
    os.makedirs(out, exist_ok=True)
    for r in runs_for(sha):
        arts = get(f"/repos/{REPO}/actions/runs/{r['id']}/artifacts", per_page=100)["artifacts"]
        for art in arts:
            if a.name and art["name"] not in a.name:
                continue
            dest = os.path.join(out, art["name"])
            if os.path.isdir(dest):
                print(f"skip {art['name']} (exists)")
                continue
            z = S.get(art["archive_download_url"])
            z.raise_for_status()
            zipfile.ZipFile(io.BytesIO(z.content)).extractall(dest)
            print(f"got {art['name']} ({art['size_in_bytes'] // 1024} KiB) -> {dest}")
    with open(os.path.join(out, "SHA"), "w") as f:
        f.write(sha + "\n")
    print(out)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "wait", "fetch"):
        s = sub.add_parser(name)
        s.add_argument("--sha")
        s.add_argument("--branch")
        if name == "wait":
            s.add_argument("--timeout", type=int, default=3600)
        if name == "fetch":
            s.add_argument("--out")
            s.add_argument("--name", nargs="*")
    s = sub.add_parser("jobs")
    s.add_argument("run_id")
    s = sub.add_parser("log")
    s.add_argument("job_id")
    s.add_argument("--tail", type=int, default=80)
    a = p.parse_args()
    {"status": cmd_status, "wait": cmd_wait, "fetch": cmd_fetch,
     "jobs": cmd_jobs, "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    main()
