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

Each rule carries its own reasoning in `why`, so the checklist prose does not
have to repeat it. Every hit is still a **candidate, not a finding**: the scan
cannot see context, so before reporting anything, confirm the line is what it
looks like, check the repo's own rules permit the objection, and drop the hit if
the surrounding code makes it correct. Respect `cap` — a rule that matches
eleven times is one comment, not eleven.
"""

import argparse
import json
import os
import re
import subprocess
import sys

# lang    which file extensions the rule applies to (see EXT)
# id      stable identifier, used in output and to gate by path
# severity  triage hint only; the verdict comes from severity-and-output.md
# cap     most comments this rule may produce in one review
# pattern regex matched against the added line
# message the one-line claim
# why     what the reviewer needs to phrase the comment and pick a severity
RULES = [
    {"lang": "java", "id": "java.var", "severity": "nitpick", "cap": 1,
     "pattern": r"(?<![\w.])var\s+\w+\s*(?:=|:|\))",
     "message": "`var` instead of an explicit type.",
     "why": "This skill prescribes explicit types. A reader of the diff, or of a "
            "stack trace months from now, should see what the variable is "
            "without inferring it from the right-hand side. `var` also hides a "
            "changed return type: a factory that switches from List<Customer> to "
            "List<CustomerSummary> silently retypes every var that consumed it. "
            "Ask for the type. NITPICK unless the inferred type is genuinely "
            "unclear at the call site, then IMPROVEMENT. Anonymous classes and "
            "intersection types have no denotable name and are the exception. If "
            "the repo's own rules endorse var, follow the repo."},

    {"lang": "java", "id": "java.mapped-association",
     "severity": "improvement", "cap": 2,
     "pattern": r"@(ManyToOne|OneToMany|ManyToMany|OneToOne)\b",
     "message": "Mapped JPA association added.",
     "why": "This skill prescribes a scalar id column plus a per-query "
            "projection, which avoids both fetch strategies rather than choosing "
            "between them: EAGER drags the association through every load path "
            "application-wide; LAZY defers the cost to an unpredictable "
            "dereference and throws LazyInitializationException once the session "
            "has closed. No fetch strategy fixes either — removing the mapping "
            "does. Ask for a scalar id plus a @Query with an explicit join "
            "returning a projection or DTO. See pr-review-java/persistence-sql.md "
            "for the N+1 shapes that replace it."},

    {"lang": "java", "id": "java.enum-ordinal", "severity": "blocker", "cap": 3,
     "pattern": r"@Enumerated\b(?!\s*\(\s*EnumType\s*\.\s*STRING)",
     "message": "Enum persisted by ordinal, explicitly or by default.",
     "why": "Reordering or inserting an enum constant silently changes the "
            "meaning of every row already written. No error, no migration — the "
            "data just means something else. Use @Enumerated(EnumType.STRING). On "
            "an existing column that also needs a data migration, so say so."},

    {"lang": "java", "id": "java.sql-concat", "severity": "blocker", "cap": 5,
     "pattern": r"\"[^\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b[^\"]*\"\s*\+",
     "message": "SQL built by string concatenation.",
     "why": "Injection unless every appended value is provably not user input — "
            "check what reaches the parameter before reporting. Bind parameters "
            "instead. A blocker when any input is user-controlled, including "
            "indirectly through a header, a filename, or a sort field."},

    {"lang": "java", "id": "java.select-star", "severity": "improvement",
     "cap": 3,
     "pattern": r"\bSELECT\s+\*",
     "message": "`SELECT *`.",
     "why": "Breaks silently when a column is added or reordered, fetches more "
            "than the code needs, and prevents an index-only scan."},

    {"lang": "java", "id": "java.print-stack-trace",
     "severity": "improvement", "cap": 2,
     "pattern": r"\.printStackTrace\s*\(",
     "message": "`printStackTrace()` instead of the logger.",
     "why": "Writes outside the log pipeline: no level, no correlation id, "
            "invisible to log search — so the failure is undiscoverable in "
            "production."},

    {"lang": "java", "id": "java.sysout", "severity": "improvement", "cap": 2,
     "pattern": r"\bSystem\s*\.\s*(out|err)\s*\.\s*print",
     "message": "`System.out`/`System.err` in application code.",
     "why": "Bypasses logging entirely: no level, no structure, no retention."},

    {"lang": "java", "id": "java.cached-thread-pool",
     "severity": "improvement", "cap": 1,
     "pattern": r"Executors\s*\.\s*newCachedThreadPool\s*\(",
     "message": "`newCachedThreadPool` is unbounded.",
     "why": "Under load it creates threads until the JVM dies, and the queue "
            "never applies backpressure. Bound the pool and the queue, name the "
            "threads, set a rejection policy, and shut it down on stop."},

    {"lang": "java", "id": "java.parallel-stream", "severity": "improvement",
     "cap": 2,
     "pattern": r"\.parallelStream\s*\(",
     "message": "`parallelStream` runs on the common ForkJoinPool.",
     "why": "One blocking task there starves every other user of the pool in the "
            "JVM. Almost always wrong in request-handling code — and check the "
            "work is even CPU-bound before accepting it anywhere."},

    {"lang": "java", "id": "java.simple-date-format",
     "severity": "improvement", "cap": 2,
     "pattern": r"new\s+SimpleDateFormat\s*\(",
     "message": "`SimpleDateFormat`.",
     "why": "Not thread-safe: as a shared or static field it corrupts output "
            "under concurrency, intermittently and invisibly. java.time "
            "formatters are immutable."},

    {"lang": "java", "id": "java.optional-get", "severity": "improvement",
     "cap": 3,
     "pattern": r"\.get\s*\(\s*\)\s*;?\s*$",
     "message": "Possible `Optional.get()` with no presence check.",
     "why": "Verify the receiver is an Optional before reporting — this pattern "
            "also matches any no-arg getter. If it is one, prefer orElseThrow "
            "with a meaningful exception."},

    {"lang": "java", "id": "java.empty-catch", "severity": "blocker", "cap": 3,
     "pattern": r"catch\s*\([^)]*\)\s*\{\s*\}",
     "message": "Empty catch block.",
     "why": "The caller sees success, the cause never reaches a log, and the next "
            "failure on that path is undiagnosable. If the exception really is "
            "expected, say so in a comment and log at debug."},

    {"lang": "java", "id": "java.mybatis-interpolation",
     "severity": "blocker", "cap": 5,
     "pattern": r"\$\{[^}]+\}",
     "message": "MyBatis `${}` interpolates straight into the SQL.",
     "why": "`#{}` binds, `${}` concatenates. On any user-controlled value this "
            "is injection. Legitimate only for a statically-known identifier such "
            "as a table or column name — and check where that comes from too."},

    {"lang": "java", "id": "java.thread-sleep", "severity": "nitpick", "cap": 2,
     "pattern": r"Thread\s*\.\s*sleep\s*\(",
     "message": "`Thread.sleep`.",
     "why": "In a test it is flaky on a loaded CI box and slow everywhere else — "
            "wait for the condition. In production code it usually hides a "
            "missing await, a retry with no backoff, or a polling loop."},

    {"lang": "ts", "id": "ts.console", "severity": "nitpick", "cap": 1,
     "pattern": r"\bconsole\s*\.\s*(log|debug|info)\s*\(",
     "message": "Leftover console logging.",
     "why": "Ships to users' browsers, can leak request or user data into a place "
            "anyone can read, and clutters the console for the next debugger."},

    {"lang": "ts", "id": "ts.any", "severity": "improvement", "cap": 3,
     "pattern": r":\s*any\b|\bas\s+any\b",
     "message": "`any` disables type checking.",
     "why": "Everything downstream of an `any` is unchecked, so the errors it "
            "hides surface far from the line that caused them. `unknown` plus a "
            "narrowing check keeps the safety; a real interface is better still."},

    {"lang": "ts", "id": "ts.ts-ignore", "severity": "improvement", "cap": 2,
     "pattern": r"@ts-(ignore|nocheck)",
     "message": "`@ts-ignore` / `@ts-nocheck`.",
     "why": "Stays suppressed after the surrounding code changes, hiding errors "
            "nobody chose to accept. `@ts-expect-error` fails the build once it "
            "is no longer needed, which is the version you want."},

    {"lang": "ts", "id": "ts.dangerous-html", "severity": "blocker", "cap": 2,
     "pattern": r"dangerouslySetInnerHTML",
     "message": "`dangerouslySetInnerHTML`.",
     "why": "XSS unless the value is sanitised or provably constant. Trace where "
            "the HTML comes from — user input, an API response, and a CMS field "
            "all count as untrusted."},

    {"lang": "ts", "id": "ts.target-blank", "severity": "improvement", "cap": 2,
     "pattern": r"target=[\"']_blank[\"'](?![^>]*rel=)",
     "message": "`target=\"_blank\"` without `rel=\"noopener\"`.",
     "why": "The opened page gets a handle on this window through window.opener "
            "and can navigate it elsewhere. Modern browsers imply noopener for "
            "_blank, so this is milder than it used to be, but the attribute is "
            "the only guarantee."},

    {"lang": "ts", "id": "ts.test-only", "severity": "blocker", "cap": 1,
     "pattern": r"\b(describe|it|test)\s*\.\s*only\s*\(",
     "message": "`.only` left in a test file.",
     "why": "Every other test in that file silently stops running and CI goes "
            "green having executed one case. This is how a regression ships after "
            "the tests 'passed'."},

    {"lang": "ts", "id": "ts.index-key", "severity": "improvement", "cap": 2,
     "pattern": r"key=\{\s*(index|i|idx)\s*\}",
     "message": "Array index used as a React `key`.",
     "why": "On reorder, insert, or delete React reuses the wrong DOM node, so "
            "input values, focus, and animation state attach to the wrong row. "
            "Use a stable id from the data. Harmless only for a list that never "
            "changes order or length."},

    {"lang": "any", "id": "any.todo", "severity": "nitpick", "cap": 1,
     "pattern": r"\b(TODO|FIXME|XXX|HACK)\b",
     "message": "TODO/FIXME added by this PR.",
     "why": "Ask whether it is tracked anywhere. An untracked TODO is a decision "
            "to forget, and this is the last moment anyone will read it."},

    {"lang": "any", "id": "any.debugger", "severity": "blocker", "cap": 1,
     "pattern": r"^\s*debugger\s*;?\s*$",
     "message": "`debugger` statement left in the diff.",
     "why": "Halts execution for anyone with devtools open."},

    {"lang": "any", "id": "any.hardcoded-secret", "severity": "blocker",
     "cap": 5,
     "pattern": r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*"
                r"[\"'][^\"']{6,}",
     "message": "Possible hardcoded credential.",
     "why": "Verify it is not a test fixture or a placeholder before reporting. If "
            "it is real, deleting the line is not enough: it is in git history and "
            "needs rotating, and that belongs in the comment."},
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

# Some patterns are also valid syntax elsewhere; only look where they mean what
# the rule says they mean.
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


def applies(rule, path):
    gate = PATH_GATE.get(rule["id"])
    if gate and not gate.search(path):
        return False
    exts = EXT[rule["lang"]]
    return exts is None or path.endswith(exts)


def scan(diff):
    hits = []
    for path, line_no, text in added_lines(diff):
        if SKIP.search(path):
            continue
        stripped = text.strip()
        if stripped.startswith(("//", "*", "/*", "#")) and "TODO" not in stripped:
            continue                      # comment-only line
        for rule in RULES:
            if not applies(rule, path):
                continue
            if re.search(rule["pattern"], text):
                hits.append({
                    "file": path,
                    "line": line_no,
                    "rule": rule["id"],
                    "severity": rule["severity"],
                    "cap": rule["cap"],
                    "message": rule["message"],
                    "why": rule["why"],
                    "code": stripped[:160],
                })
    return hits


def wrap(text, width=74, indent=" " * 11):
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return ("\n" + indent).join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff-file")
    ap.add_argument("--pr", help="PR number; shells out to `gh pr diff`")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="print the rules")
    ap.add_argument("--brief", action="store_true",
                    help="omit the reasoning, print one line per hit")
    args = ap.parse_args()

    if args.list:
        for rule in RULES:
            print(f"{rule['id']:<32} {rule['severity']:<12} "
                  f"cap {rule['cap']}  [{rule['lang']}] {rule['message']}")
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

    counts = {}
    for h in hits:
        counts[h["rule"]] = counts.get(h["rule"], 0) + 1

    by_file = {}
    for h in hits:
        by_file.setdefault(h["file"], []).append(h)

    shown = {}
    for path in sorted(by_file):
        print(f"\n{path}")
        for h in sorted(by_file[path], key=lambda x: x["line"]):
            print(f"  {h['line']:>5}  {h['severity']:<11} {h['rule']}")
            print(f"         {h['code']}")
            print(f"         {h['message']}")
            seen = shown.get(h["rule"], 0)
            if not args.brief and seen == 0:
                print(f"         why: {wrap(h['why'])}")
            shown[h["rule"]] = seen + 1

    over_cap = [(r, n, next(x["cap"] for x in hits if x["rule"] == r))
                for r, n in counts.items()
                if n > next(x["cap"] for x in hits if x["rule"] == r)]
    print(f"\n{len(hits)} candidate(s) in {len(by_file)} file(s).")
    for rule_id, n, cap in sorted(over_cap):
        print(f"  {rule_id}: {n} hits, cap {cap} — raise it once and say it "
              f"applies in {n} places.")
    print("Each hit is a candidate: verify it in context, check the repo's own "
          "rules allow the objection, and drop what does not survive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
