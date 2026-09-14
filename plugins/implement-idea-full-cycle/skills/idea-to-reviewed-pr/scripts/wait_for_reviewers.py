#!/usr/bin/env python3
# Step 2 — block until the PR's automated reviewers have had their say.
#
#   Usage: scripts/wait_for_reviewers.py <pr-number> [--cap-seconds N]
#   Prints: a one-line verdict, then a short status block.
#   Exits 0 whether or not the checks finished, 2 on bad usage.
#
# Why this waits at all: the inline review in Step 3 is worth more if the bot reviewers
# (Sonar, dependency-review, Dependabot) have already posted, because Step 4 then fixes
# their findings in the same pass instead of leaving them for the developer. Those bots
# take minutes, and `ship.py` returns the moment the PR exists.
#
# Why it never fails the run: the wait is an optimisation, not a gate. The bots break,
# hang, or silently never report often enough that treating a timeout as fatal would
# strand finished work. So every outcome — settled, timed out, gh unusable — exits 0 and
# says which one it was. The caller proceeds regardless and reports what it saw.
#
# Why the cap defaults to 540s: the Bash tool's ceiling is 600s. Finishing comfortably
# under it means the timeout kills nothing mid-write and the caller always gets the
# status block, which is the whole point of the step.
#
# Python rather than bash for the same reason as the sibling scripts: `python <file>`
# behaves identically in Git Bash, Windows PowerShell 5.1 and pwsh, and a .sh file only
# runs in the first of those.
import json
import shutil
import subprocess
import sys
import time

GH = shutil.which("gh")
POLL_SECONDS = 20
DEFAULT_CAP_SECONDS = 540

# statusCheckRollup states that mean "still working". Anything else is a reported result,
# including failures — a red check is settled, and Step 3 should review the PR anyway.
UNFINISHED = {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED"}


def die(code, *lines):
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(code)


def gh_json(*args):
    """Runs gh and parses stdout as JSON. Returns None on any failure — see header."""
    try:
        done = subprocess.run([GH, *args], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if done.returncode:
        return None
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        return None


def check_state(check):
    """statusCheckRollup mixes two shapes: Actions runs use `status`, commit statuses `state`."""
    return (check.get("status") or check.get("state") or "").upper()


def poll(pr):
    """One sample of the PR. Returns (unfinished_count, total_count, review_comment_count)."""
    view = gh_json("pr", "view", pr, "--json", "statusCheckRollup")
    if view is None:
        return None
    checks = view.get("statusCheckRollup") or []
    unfinished = sum(1 for c in checks if check_state(c) in UNFINISHED)

    # Line-level review comments live on a different endpoint than `gh pr view` exposes.
    # This is the number Step 4 actually works through, so it is worth the extra call.
    comments = gh_json(
        "api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{pr}/comments",
        "--jq", "length",
    )
    if isinstance(comments, int):
        comment_count = comments
    elif isinstance(comments, list):
        comment_count = sum(comments)  # --paginate emits one length per page
    else:
        comment_count = -1

    return unfinished, len(checks), comment_count


def report(verdict, unfinished, total, comments, waited):
    print(verdict)
    print(f"checks: {total - unfinished}/{total} reported" if total else "checks: none found")
    print(f"review comments on PR: {comments}" if comments >= 0 else "review comments: unknown")
    print(f"waited: {waited}s")


def main():
    argv = sys.argv[1:]
    cap = DEFAULT_CAP_SECONDS
    if "--cap-seconds" in argv:
        i = argv.index("--cap-seconds")
        try:
            cap = int(argv[i + 1])
        except (IndexError, ValueError):
            die(2, "usage: wait_for_reviewers.py <pr-number> [--cap-seconds N]")
        del argv[i:i + 2]
    if len(argv) != 1 or not argv[0].isdigit():
        die(2, "usage: wait_for_reviewers.py <pr-number> [--cap-seconds N]")
    if GH is None:
        report("PROCEEDING: gh not on PATH, nothing to wait on", 0, 0, -1, 0)
        return

    pr = argv[0]
    started = time.monotonic()
    last = None

    while True:
        sample = poll(pr)
        waited = int(time.monotonic() - started)

        if sample is None:
            # A single failed poll is usually a blip; give up only if the first one failed,
            # since that means gh cannot see this PR at all and waiting proves nothing.
            if last is None:
                report("PROCEEDING: gh could not read the PR", 0, 0, -1, waited)
                return
        else:
            last = sample
            unfinished, total, comments = sample
            if unfinished == 0:
                verdict = ("SETTLED: all checks reported" if total
                           else "SETTLED: no checks configured on this PR")
                report(verdict, unfinished, total, comments, waited)
                return

        if waited + POLL_SECONDS > cap:
            unfinished, total, comments = last
            report(
                f"TIMED OUT after {cap}s with {unfinished} check(s) still running — "
                "proceeding anyway",
                unfinished, total, comments, waited,
            )
            return

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
