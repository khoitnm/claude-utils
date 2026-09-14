#!/usr/bin/env python3
# The one source of truth about where a run has got to. Called three times per run.
#
#   Usage: scripts/pr_state.py <branch> [--since <sha>] [--base <ref>]
#   Prints: a fixed key/value block, verdict last.
#   Exits 0 whether or not it found a PR, 2 on bad usage.
#
# Three jobs, all of which the orchestrator otherwise has to take a subagent's word for:
#
#   1. Resume. Step 1 (ticket + implement + PR) is not idempotent: it files a tracker ticket,
#      so re-running a died run files a second one. The skill asks here first, and skips
#      Step 1 when the branch already has an open PR.
#   2. The round cap. "One review round" was a sentence in the skill, which is a rule a long
#      run can drift past. Counting commits that carry the "Review catch" marker makes it a
#      fact instead.
#   3. Verification. A subagent reports what it believes it did; this reports what is actually
#      on the PR and in git. `--since <sha>` adds the commit subjects and a --stat, which is
#      how the parent sees the fix round's work without reading one line of the diff — a few
#      hundred tokens no matter how large the change was. `unpushed_commits` is part of the
#      same job: a local commit and a shipped one look the same in a log, and only one of
#      them is on the PR.
#
# Nothing here fails the run. Every outcome is a line the caller reports, because a run that
# has already pushed work must not be abandoned over a failed `gh` call.
#
# Python rather than bash for the same reason as the sibling scripts: `python <file>` behaves
# identically in Git Bash, Windows PowerShell 5.1 and pwsh, and a .sh file only runs in the
# first of those.
import json
import shutil
import subprocess
import sys

GH = shutil.which("gh")
GIT = shutil.which("git")

# handle-review-comments already tells the fixer to write "Review catch (<reviewer>)" into
# the commit body. Counting that marker is what turns the one-round cap into a check. Keep the
# two in step: if that skill's wording changes, this stops counting and the cap stops working.
REVIEW_COMMIT_MARKER = "Review catch"


def default_base():
    """The ref to count review commits since, when --base is not given.

    Asks GitHub for the repo's own default branch rather than assuming one: this plugin runs
    against repos that base on `dev`, `master` and `main`, and guessing wrong makes
    response_commits meaningless instead of merely absent. `origin/` prefixed because the
    local copy of the branch may be stale or missing entirely.
    """
    out = run([GH, "repo", "view", "--json", "defaultBranchRef",
               "--jq", ".defaultBranchRef.name"])
    return f"origin/{out}" if out else None


def die(code, *lines):
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(code)


def run(cmd):
    """Returns stdout, or None on any failure — see the header on why nothing here is fatal."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def find_pr(branch):
    """The open PR for this branch, or None. `--state open` is deliberate: a closed PR means
    the branch was abandoned, and resuming onto it would push to something nobody is reading."""
    out = run([GH, "pr", "list", "--head", branch, "--state", "open",
               "--json", "number,url,title", "--limit", "1"])
    if not out:
        return None
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return None
    return items[0] if items else None


def comment_counts(pr):
    """(total, unanswered) line-level review comments.

    Unanswered means a top-level comment (in_reply_to_id is null) that nothing replies to.
    That is the number Step 4 still owes work on, and the number that makes replying
    idempotent: a resumed run skips threads it already answered."""
    out = run([GH, "api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{pr}/comments"])
    if not out:
        return -1, -1
    try:
        # --paginate concatenates one JSON array per page; normalise to a single list.
        decoder, idx, comments = json.JSONDecoder(), 0, []
        while idx < len(out):
            page, idx = decoder.raw_decode(out, idx)
            comments.extend(page)
            while idx < len(out) and out[idx] in " \r\n\t":
                idx += 1
    except (json.JSONDecodeError, ValueError):
        return -1, -1

    replied_to = {c.get("in_reply_to_id") for c in comments if c.get("in_reply_to_id")}
    top_level = [c for c in comments if not c.get("in_reply_to_id")]
    unanswered = sum(1 for c in top_level if c.get("id") not in replied_to)
    return len(comments), unanswered


def response_commits(branch, base):
    """Commits on this branch carrying the review-fix marker. The round cap reads this."""
    if not base:
        return -1
    out = run([GIT, "log", f"{base}..{branch}", "--oneline", f"--grep={REVIEW_COMMIT_MARKER}"])
    if out is None:
        return -1
    return len([line for line in out.splitlines() if line.strip()])


def unpushed_commits(branch):
    """How many commits are on the local branch but not on origin yet.

    Without this, `commits_since` is a trap: it reads the local log, so a fix round that
    committed and never pushed looks identical to one that shipped. GitHub would still be
    showing the original code, and the replies would cite shas that 404.

    Returns -1 for "unknown", -2 for "no local origin/<branch> ref to compare against".
    The -2 case does not mean the branch is unpushed — a branch pushed from another clone,
    or never fetched here, has no local remote-tracking ref either. Saying "not pushed"
    there would be a lie in the one place this script exists to stop lies.
    """
    if run([GIT, "rev-parse", "--verify", "--quiet", f"origin/{branch}"]) is None:
        return -2
    out = run([GIT, "rev-list", "--count", f"origin/{branch}..{branch}"])
    if out is None or not out.isdigit():
        return -1
    return int(out)


def since_section(sha):
    """What changed since the caller last looked — subjects and a --stat, never a diff."""
    commits = run([GIT, "log", f"{sha}..HEAD", "--oneline"]) or ""
    lines = [ln for ln in commits.splitlines() if ln.strip()]
    print(f"commits_since: {len(lines)}")
    for line in lines:
        print(f"  {line}")
    stat = run([GIT, "diff", "--stat", f"{sha}..HEAD"]) or ""
    stat_lines = [ln for ln in stat.splitlines() if ln.strip()]
    print(f"files_touched: {max(len(stat_lines) - 1, 0)}")
    for line in stat_lines:
        print(f"  {line.strip()}")


USAGE = "usage: pr_state.py <branch> [--since <sha>] [--base <ref>]"


def take_option(argv, name):
    """Pulls `--name <value>` out of argv, or None. Exits 2 if the value is missing."""
    if name not in argv:
        return None
    i = argv.index(name)
    try:
        value = argv[i + 1]
    except IndexError:
        die(2, USAGE)
    del argv[i:i + 2]
    return value


def main(argv):
    since = take_option(argv, "--since")
    base = take_option(argv, "--base")
    if len(argv) != 1 or not argv[0]:
        die(2, USAGE)
    if GIT is None or GH is None:
        print("branch: unknown")
        print("verdict: TOOLING_MISSING — git or gh not on PATH, decide by hand")
        return

    branch = argv[0]
    base = base or default_base()
    print(f"branch: {branch}")
    print(f"base: {base or 'unknown'}")

    pr = find_pr(branch) if GH else None
    if pr is None:
        print("pr: none")
        if since:
            since_section(since)
        print("verdict: FRESH_RUN — no open PR for this branch, start at Step 1")
        return

    number = pr["number"]
    print(f"pr: {number} {pr['url']}")

    total, unanswered = comment_counts(number)
    print(f"review_comments: {total}" if total >= 0 else "review_comments: unknown")
    print(f"unanswered_comments: {unanswered}" if unanswered >= 0
          else "unanswered_comments: unknown")

    responses = response_commits(branch, base)
    print(f"response_commits: {responses}" if responses >= 0 else "response_commits: unknown")

    ahead = unpushed_commits(branch)
    print("unpushed_commits: unknown (no local origin/%s ref — run git fetch)" % branch
          if ahead == -2
          else "unpushed_commits: unknown" if ahead < 0
          else f"unpushed_commits: {ahead}")

    if since:
        since_section(since)

    if responses >= 1:
        print("verdict: CAP_REACHED — the fix round already ran on this branch, stop at Step 5")
    elif responses < 0:
        # Silently falling through would enforce the round cap on faith, which is the habit
        # this script exists to break. Say the check did not run and let the caller decide.
        print("verdict: CAP_UNCHECKED — could not count commits (no local branch, or base "
              "branch unknown), do not run Step 4")
    elif unanswered == 0 and total > 0:
        print("verdict: ALREADY_ANSWERED — every comment has a reply, skip Step 4")
    else:
        print("verdict: RESUME — PR exists, skip Step 1 and continue from Step 2")


if __name__ == "__main__":
    # Windows hands Python a cp1252 stdout that turns the em-dashes above into a replacement
    # character, and translates every \n to \r\n. Both land in the model's context as noise.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", newline="\n")
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        # One line, never a traceback: this output lands in the model's context, and a stack
        # dump costs more tokens than it explains.
        die(1, f"pr_state.py failed: {type(exc).__name__}: {exc}")
