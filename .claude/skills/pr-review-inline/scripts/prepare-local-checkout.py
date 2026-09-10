#!/usr/bin/env python3
"""Put the PR head on disk so the review can read changed files locally.

Reading changed files from a checkout is faster than fetching each one through
the GitHub MCP server, and it lets you grep for the sibling change that was
missed. But it is only safe if the files on disk *are* the PR head, so this
script fetches refs/pull/<n>/head and reports a path only once the checkout is
verified to sit at that SHA.

    python scripts/prepare-local-checkout.py --pr 548
    python scripts/prepare-local-checkout.py https://github.com/o/r/pull/548
    python scripts/prepare-local-checkout.py --pr 548 --check     # report, change nothing
    python scripts/prepare-local-checkout.py --pr 548 --in-place  # move the current checkout
    python scripts/prepare-local-checkout.py --pr 548 --cleanup   # remove the worktree

By default it adds a detached worktree beside the repo rather than switching
branches, so a half-finished branch in the main checkout is never disturbed.
`--in-place` switches the current checkout instead, and refuses if it is dirty.

Exit codes: 0 the path is ready to read from, 3 it is not (the reason is
printed - read the changed files through the GitHub MCP server instead), 1 the
arguments or the repo are wrong.
"""

import argparse
import json
import os
import re
import subprocess
import sys

NOT_READY = 3


def git(*args, cwd=None, check=True):
    """Run git and return stdout stripped. Raises on failure unless check=False."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        if check:
            detail = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(detail or "git " + " ".join(args) + " failed")
        return ""
    return proc.stdout.strip()


def gh_json(args, cwd):
    """Run a gh command expected to emit JSON. None if gh is missing or fails."""
    try:
        proc = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def parse_pr_arg(value):
    """Accept 548, #548, or any .../<owner>/<repo>/pull/548[/anything] URL."""
    if value is None:
        return None, None
    text = value.strip().lstrip("#")
    if text.isdigit():
        return int(text), None
    match = re.search(r"[:/]([^/]+)/([^/]+)/pull/(\d+)", text)
    if match:
        return int(match.group(3)), match.group(1) + "/" + match.group(2)
    return None, None


def remote_slug(repo_root):
    """owner/repo from the origin URL, for display only."""
    url = git("remote", "get-url", "origin", cwd=repo_root, check=False)
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    return match.group(1) + "/" + match.group(2) if match else None


def head_sha(repo_root, number):
    """The PR head SHA from the remote - the authority on what to check out.

    ls-remote comes first because it needs no gh install and no auth beyond the
    fetch that follows it.
    """
    line = git("ls-remote", "origin", "refs/pull/{}/head".format(number),
               cwd=repo_root, check=False)
    if line:
        return line.split()[0]
    data = gh_json(["pr", "view", str(number), "--json", "headRefOid"], repo_root)
    return data.get("headRefOid") if data else None


def is_dirty(path):
    return bool(git("status", "--porcelain", "--untracked-files=no", cwd=path, check=False))


def default_worktree_path(repo_root, number):
    """Beside the repo, not inside it: keeps the second copy out of the repo's
    own status, ignore rules, and IDE indexing."""
    root = os.path.abspath(repo_root)
    return os.path.join(os.path.dirname(root), ".pr-review",
                        "{}-pr-{}".format(os.path.basename(root), number))


def report(result, as_json):
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        shown = {k: v for k, v in result.items() if v is not None}
        width = max(len(k) for k in shown)
        for key, value in shown.items():
            print("{}  {}".format(key.ljust(width), value))
    return 0 if result["status"] == "ready" else NOT_READY


def do_cleanup(repo_root, worktree, local_ref, number, as_json):
    removed = []
    if os.path.isdir(worktree):
        if is_dirty(worktree):
            return report({"status": "not-ready", "pr": number, "path": worktree,
                           "reason": "the worktree has uncommitted changes; not removing it"},
                          as_json)
        git("worktree", "remove", "--force", worktree, cwd=repo_root, check=False)
        removed.append(worktree)
    git("update-ref", "-d", local_ref, cwd=repo_root, check=False)
    git("worktree", "prune", cwd=repo_root, check=False)
    return report({"status": "ready", "pr": number, "mode": "cleanup",
                   "removed": ", ".join(removed) or "nothing to remove"}, as_json)


def do_in_place(repo_root, sha, number, slug, as_json):
    if is_dirty(repo_root):
        return report({
            "status": "not-ready", "pr": number, "repo": slug, "head": sha,
            "reason": "{} has uncommitted changes; refusing to switch it".format(repo_root),
            "next": "commit or stash them, or drop --in-place to use a worktree",
        }, as_json)
    was = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root, check=False)
    try:
        git("checkout", "--detach", sha, cwd=repo_root)
    except RuntimeError as error:
        return report({"status": "not-ready", "pr": number, "repo": slug, "head": sha,
                       "reason": "checkout failed: {}".format(error),
                       "next": "read the changed files through the GitHub MCP server"}, as_json)
    return report({
        "status": "ready", "pr": number, "repo": slug, "head": sha,
        "mode": "in-place (detached HEAD)", "path": repo_root,
        "restore": "git -C {} checkout {}".format(repo_root, was) if was and was != "HEAD" else None,
    }, as_json)


def do_worktree(repo_root, worktree, sha, number, slug, as_json):
    if os.path.isdir(worktree):
        if is_dirty(worktree):
            return report({
                "status": "not-ready", "pr": number, "repo": slug, "head": sha, "path": worktree,
                "reason": "the worktree has uncommitted changes; it may not match the PR head",
                "next": "inspect it, then re-run with --cleanup",
            }, as_json)
        if git("rev-parse", "HEAD", cwd=worktree, check=False) == sha:
            mode = "worktree (reused)"
        else:
            # A re-review after new commits landed: same worktree, newer head.
            try:
                git("checkout", "--detach", sha, cwd=worktree)
            except RuntimeError as error:
                return report({"status": "not-ready", "pr": number, "repo": slug, "head": sha,
                               "path": worktree,
                               "reason": "could not update the worktree: {}".format(error),
                               "next": "re-run with --cleanup, then again to recreate it"}, as_json)
            mode = "worktree (updated to new head)"
    else:
        os.makedirs(os.path.dirname(worktree), exist_ok=True)
        try:
            git("worktree", "add", "--detach", worktree, sha, cwd=repo_root)
        except RuntimeError as error:
            return report({"status": "not-ready", "pr": number, "repo": slug, "head": sha,
                           "reason": "could not add a worktree: {}".format(error),
                           "next": "read the changed files through the GitHub MCP server"}, as_json)
        mode = "worktree (new)"

    return report({
        "status": "ready", "pr": number, "repo": slug, "head": sha, "mode": mode,
        "path": worktree,
        "note": "read changed files, and this repo's own CLAUDE.md, from this path",
        "cleanup": cleanup_hint(repo_root, worktree, number),
    }, as_json)


def cleanup_hint(repo_root, worktree, number):
    """The exact command that undoes this run, absolute so it works from any cwd
    and repeating --path when the worktree is not where the default would put it."""
    command = 'python "{}" --repo-dir "{}" --pr {} --cleanup'.format(
        os.path.abspath(__file__), repo_root, number)
    if worktree != default_worktree_path(repo_root, number):
        command += ' --path "{}"'.format(worktree)
    return command


def main():
    parser = argparse.ArgumentParser(
        description="Check out a PR head locally so a review can read files from disk.")
    parser.add_argument("pr", nargs="?", help="PR number or URL")
    parser.add_argument("--pr", dest="pr_flag", help="PR number or URL")
    parser.add_argument("--repo-dir", default=".", help="the local clone (default: cwd)")
    parser.add_argument("--path", help="worktree location (default: ../.pr-review/<repo>-pr-<n>)")
    parser.add_argument("--in-place", action="store_true",
                        help="switch the current checkout instead of adding a worktree")
    parser.add_argument("--check", action="store_true",
                        help="report whether the current checkout is at the PR head; change nothing")
    parser.add_argument("--cleanup", action="store_true",
                        help="remove this PR's worktree and fetched ref")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    try:
        repo_root = git("rev-parse", "--show-toplevel", cwd=args.repo_dir)
    except FileNotFoundError:
        print("git is not on PATH", file=sys.stderr)
        return 1
    except (RuntimeError, OSError):
        print("not a git repository: {}".format(os.path.abspath(args.repo_dir)), file=sys.stderr)
        return 1

    raw = args.pr_flag or args.pr
    number, slug = parse_pr_arg(raw)
    if number is None and raw:
        print("could not read a PR number from {!r}".format(raw), file=sys.stderr)
        return 1
    if number is None:
        data = gh_json(["pr", "view", "--json", "number"], repo_root)
        number = data.get("number") if data else None
    if number is None:
        print("no PR number given, and gh could not resolve one for this branch", file=sys.stderr)
        return 1

    slug = slug or remote_slug(repo_root)
    local_ref = "refs/pr-review/{}".format(number)
    worktree = os.path.abspath(args.path) if args.path else default_worktree_path(repo_root, number)

    # Stale worktree metadata outlives a manually deleted directory and makes
    # every later `worktree add` for that path fail.
    git("worktree", "prune", cwd=repo_root, check=False)

    if args.cleanup:
        return do_cleanup(repo_root, worktree, local_ref, number, args.json)

    sha = head_sha(repo_root, number)
    if not sha:
        return report({
            "status": "not-ready", "pr": number, "repo": slug,
            "reason": "could not resolve refs/pull/{}/head from origin "
                      "(wrong number, no access, or no network)".format(number),
            "next": "read the changed files through the GitHub MCP server",
        }, args.json)

    current = git("rev-parse", "HEAD", cwd=repo_root, check=False)

    # Uncommitted changes mean the files on disk are not the PR head, whatever
    # HEAD says - so a dirty checkout is never reported as a source of truth.
    usable = current == sha and not is_dirty(repo_root)

    if args.check:
        if usable:
            reason = None
        elif current == sha:
            reason = "the checkout is at the PR head but has uncommitted changes"
        else:
            reason = "the checkout is at {}, not the PR head".format(current[:12] or "nothing")
        return report({
            "status": "ready" if usable else "not-ready",
            "pr": number, "repo": slug, "head": sha,
            "path": repo_root if usable else None,
            "reason": reason,
            "next": None if usable else "re-run without --check to prepare a worktree",
        }, args.json)

    # An explicit --path is a request for that path, not for a shortcut.
    if usable and not args.in_place and not args.path:
        return report({
            "status": "ready", "pr": number, "repo": slug, "head": sha,
            "mode": "current checkout is already at the PR head", "path": repo_root,
        }, args.json)

    # Anchor the fetched commit under a real ref so it survives gc mid-review.
    try:
        git("fetch", "--no-tags", "origin",
            "+refs/pull/{}/head:{}".format(number, local_ref), cwd=repo_root)
    except RuntimeError as error:
        return report({"status": "not-ready", "pr": number, "repo": slug, "head": sha,
                       "reason": "fetch failed: {}".format(error),
                       "next": "read the changed files through the GitHub MCP server"}, args.json)

    if args.in_place:
        return do_in_place(repo_root, sha, number, slug, args.json)
    return do_worktree(repo_root, worktree, sha, number, slug, args.json)


if __name__ == "__main__":
    sys.exit(main())
