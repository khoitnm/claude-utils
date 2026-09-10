#!/usr/bin/env python3
"""Scan a PR diff for the rules a regex can decide, so the review does not spend
model attention on them.

Reads a unified diff and reports only on **added lines**. It never looks at the
working tree, so pre-existing code cannot produce a hit: a PR is only ever
flagged for what it introduces. That is deliberate — these rules are for
reviewing new code, not for failing a build over a decade of history.

    gh pr diff 548 | python scripts/scan-mechanical-rules.py
    python scripts/scan-mechanical-rules.py --diff-file pr.diff --json
    python scripts/scan-mechanical-rules.py --pr 548          # shells out to gh
    python scripts/scan-mechanical-rules.py --list            # show the rules

Every hit is a **candidate**, not a finding. The scan cannot see context, so
before reporting anything: confirm the line is what it looks like, check the
repo's own rules permit the construct you are about to object to, and drop the
hit if the surrounding code makes it correct. A false positive posted to a PR
costs more than a missed nitpick.
"""

import argparse
import json
import os
import re
import subprocess
import sys

# path, id, severity, regex, message
# severity is a hint for triage, not the final verdict — that comes from
# pr-review-shared/severity-and-output.md after a human-verified read.
RULES = [
    # ---- Java -------------------------------------------------------------
    ("java", "java.var", "nitpick",
     r"(?<![\w.])var\s+\w+\s*=",
     "`var` hides the type in the diff and in stack traces; this skill "
     "prescribes explicit types (pr-review-java/core-java.md)."),
    ("java", "java.mapped-association", "improvement",
     r"@(ManyToOne|OneToMany|ManyToMany|OneToOne)\b",
     "Mapped association added. This skill prescribes a scalar id column plus a "
     "per-query projection (pr-review-java/persistence-sql.md)."),
    ("java", "java.enum-ordinal", "blocker",
     r"@Enumerated\b(?!\s*\(\s*EnumType\s*\.\s*STRING)",
     "Enum persisted by ordinal (explicitly or by default): reordering the enum "
     "silently rewrites the meaning of every existing row. Use "
     "`EnumType.STRING`."),
    ("java", "java.sql-concat", "blocker",
     r"\"[^\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b[^\"]*\"\s*\+",
     "SQL built by string concatenation — injection unless every appended value "
     "is provably not user input. Bind parameters."),
    ("java", "java.select-star", "improvement",
     r"\bSELECT\s+\*",
     "`SELECT *` breaks when a column is added and fetches more than needed."),
    ("java", "java.print-stack-trace", "improvement",
     r"\.printStackTrace\s*\(",
     "`printStackTrace()` writes outside the log pipeline: no level, no "
     "correlation id, invisible to log search."),
    ("java", "java.sysout", "improvement",
     r"\bSystem\s*\.\s*(out|err)\s*\.\s*print",
     "`System.out`/`System.err` in application code bypasses logging."),
    ("java", "java.cached-thread-pool", "improvement",
     r"Executors\s*\.\s*newCachedThreadPool\s*\(",
     "`newCachedThreadPool` is unbounded: under load it creates threads until "
     "the JVM dies. Bound the pool and the queue."),
    ("java", "java.parallel-stream", "improvement",
     r"\.parallelStream\s*\(",
     "`parallelStream` runs on the common ForkJoinPool; one blocking task there "
     "degrades every other user of it."),
    ("java", "java.simple-date-format", "improvement",
     r"new\s+SimpleDateFormat\s*\(",
     "`SimpleDateFormat` is not thread-safe and is a real bug as a shared "
     "field. Use `java.time` formatters."),
    ("java", "java.optional-get", "improvement",
     r"\.get\s*\(\s*\)\s*;?\s*$",
     "Possible `Optional.get()` without a presence check — verify the receiver "
     "type before reporting."),
    ("java", "java.empty-catch", "blocker",
     r"catch\s*\([^)]*\)\s*\{\s*\}",
     "Empty catch block swallows the failure: the caller sees success and the "
     "cause never reaches a log."),
    ("java", "java.mybatis-interpolation", "blocker",
     r"\$\{[^}]+\}",
     "MyBatis `${}` interpolates directly into SQL. `#{}` binds. On a "
     "user-controlled value this is injection."),
    ("java", "java.thread-sleep", "nitpick",
     r"Thread\s*\.\s*sleep\s*\(",
     "`Thread.sleep` in a test is flaky on a loaded CI box; in production code "
     "it usually hides a missing await or a polling loop."),

    # ---- TypeScript / React ----------------------------------------------
    ("ts", "ts.console", "nitpick",
     r"\bconsole\s*\.\s*(log|debug|info)\s*\(",
     "Leftover console logging ships to users' browsers."),
    ("ts", "ts.any", "improvement",
     r":\s*any\b|\bas\s+any\b",
     "`any` disables checking for everything downstream of it — the errors it "
     "hides surface far from here."),
    ("ts", "ts.ts-ignore", "improvement",
     r"@ts-(ignore|nocheck)",
     "A suppressed type error stays suppressed after the code around it "
     "changes. Prefer `@ts-expect-error`, which fails once it is unnecessary."),
    ("ts", "ts.dangerous-html", "blocker",
     r"dangerouslySetInnerHTML",
     "`dangerouslySetInnerHTML` is XSS unless the value is sanitised or "
     "provably constant."),
    ("ts", "ts.target-blank", "improvement",
     r"target=[\"']_blank[\"'](?![^>]*rel=)",
     "`target=\"_blank\"` without `rel=\"noopener\"` gives the opened page a "
     "handle on this window."),
    ("ts", "ts.test-only", "blocker",
     r"\b(describe|it|test)\s*\.\s*only\s*\(",
     "`.only` left in a test file silently skips every other test in it — CI "
     "goes green having run one case."),
    ("ts", "ts.index-key", "improvement",
     r"key=\{\s*(index|i|idx)\s*\}",
     "An array index as `key` makes React reuse the wrong DOM node when the "
     "list reorders, carrying stale input state with it."),

    # ---- any language ----------------------------------------------------
    ("any", "any.todo", "nitpick",
     r"\b(TODO|FIXME|XXX|HACK)\b",
     "A TODO added by this PR: is it tracked anywhere, or is this where it "
     "dies?"),
    ("any", "any.debugger", "blocker",
     r"^\s*debugger\s*;?\s*$",
     "`debugger` statement left in the diff."),
    ("any", "any.hardcoded-secret", "blocker",
     r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*[\"'][^\"']{6,}",
     "Possible hardcoded credential. Verify it is not a test fixture or a "
     "placeholder before reporting — but if it is real, it is a blocker and the "
     "value needs rotating, not just deleting."),
]

EXT = {
    "java": (".java",),
    "ts": (".ts", ".tsx", ".js", ".jsx"),
    "any": None,
}

SKIP = re.compile(
    r"(^|/)(node_modules|target|build|dist|out|__generated__|vendor)/|"
    r"(\.min\.(js|css)|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|"
    r"\.lock|\.snap|\.svg|\.png|\.jpg|\.pdf)$")

# MyBatis interpolation is also valid shell/template syntax; only flag it where
# SQL actually lives.
PATH_GATE = {
    "java.mybatis-interpolation": re.compile(r"\.(java|xml|sql)$"),
    "java.select-star": re.compile(r"\.(java|xml|sql|kt)$"),
    "java.thread-sleep": re.compile(r"\.(java|kt)$"),
}


def added_lines(diff):
    """Yield (path, new_line_no, text) for every added line in a unified diff."""
    path, new_no = None, 0
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = None if target == "/dev/null" else re.sub(r"^b/", "", target)
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_no = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            if path:
                yield path, new_no, line[1:]
            new_no += 1
        elif line.startswith("-") or line.startswith("\\"):
            continue
        else:
            new_no += 1


def applies(rule_lang, rule_id, path):
    gate = PATH_GATE.get(rule_id)
    if gate and not gate.search(path):
        return False
    exts = EXT[rule_lang]
    return exts is None or path.endswith(exts)


def scan(diff):
    hits = []
    for path, line_no, text in added_lines(diff):
        if SKIP.search(path):
            continue
        stripped = text.strip()
        if stripped.startswith(("//", "*", "/*", "#")) and "TODO" not in stripped:
            continue                      # comment-only line
        for lang, rule_id, severity, pattern, message in RULES:
            if not applies(lang, rule_id, path):
                continue
            if re.search(pattern, text):
                hits.append({
                    "file": path,
                    "line": line_no,
                    "rule": rule_id,
                    "severity": severity,
                    "message": message,
                    "code": stripped[:160],
                })
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff-file")
    ap.add_argument("--pr", help="PR number; shells out to `gh pr diff`")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="print the rules")
    args = ap.parse_args()

    if args.list:
        for lang, rule_id, severity, pattern, message in RULES:
            print(f"{rule_id:<32} {severity:<12} [{lang}] {message}")
        return 0

    if args.pr:
        diff = subprocess.run(["gh", "pr", "diff", args.pr],
                              capture_output=True, text=True, check=True).stdout
    elif args.diff_file:
        diff = open(args.diff_file, encoding="utf-8", errors="replace").read()
    else:
        if sys.stdin.isatty():
            print("no diff on stdin; use --diff-file or --pr", file=sys.stderr)
            return 2
        diff = sys.stdin.read()

    hits = scan(diff)

    if args.json:
        print(json.dumps(hits, indent=2))
        return 0

    if not hits:
        print("no mechanical-rule hits in the added lines")
        return 0

    by_file = {}
    for h in hits:
        by_file.setdefault(h["file"], []).append(h)
    for path in sorted(by_file):
        print(f"\n{path}")
        for h in sorted(by_file[path], key=lambda x: x["line"]):
            print(f"  {h['line']:>5}  {h['severity']:<11} {h['rule']}")
            print(f"         {h['code']}")
            print(f"         -> {h['message']}")
    print(f"\n{len(hits)} candidate(s) in {len(by_file)} file(s). "
          f"Each one is a candidate: verify it in context, check the repo's own "
          f"rules allow you to object, and drop the ones that do not survive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
