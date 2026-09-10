#!/usr/bin/env python3
"""Lint the pr-review-inline checklist files.

Enforces the structural rules that keep the skill cheap to load and honest:
a token budget per file, working links, complete dispatch indexes, no
project-specific identifiers, no near-duplicate rules across files, and no
bare style preferences with no stated consequence.

    python scripts/lint-skill-docs.py            # from the skill root
    python scripts/lint-skill-docs.py --strict    # warnings become failures
    python scripts/lint-skill-docs.py --stats     # print the budget table only

Exit code 1 means a rule was violated. Wire it up with:
    git config core.hooksPath .githooks
and a hook that runs this script.
"""

import argparse
import difflib
import os
import re
import sys

# Token budgets, estimated as len(chars) / 4. Deliberately tight: the cost of a
# checklist is not the tokens, it is that a reviewer facing 12k tokens of "raise
# this" starts raising things to justify the reading.
BUDGETS = {
    "SKILL.md": 1600,
    "INDEX.md": 1800,
    "_default": 2500,
    "_total": 50000,
}

# Identifiers that mean a specific employer, repo, module, or ticket leaked into
# a checklist that is supposed to work on any codebase.
PROJECT_SPECIFIC = [
    r"\bsc-(api|app|common|onboarding|offline-job)\b",
    r"\bsop-[a-z-]+\b",
    r"\bpcc[-_][a-z-]+\b",
    # JIRA-style ticket keys, minus the standards that share their shape
    r"\b(?!(?:JSR|SHA|RFC|ISO|IEC|UTF|AES|RSA|TLS|SSL|CVE|JEP|JDK|HTTP|MD|SQL)-)"
    r"[A-Z]{2,5}-\d{3,6}\b",
    r"\bpointclickcare\b",
    r"confluence\.[a-z.]+/",
]

# A bullet that only states a preference. Without a consequence the reviewer
# cannot meet the "name the input and the wrong result" bar in
# pr-review-shared/severity-and-output.md.
PREFERENCE_ONLY = re.compile(
    r"^\s*[-*]\s+(?:Always |Never |Use |Prefer |Avoid |Do not |Don't |Consider )",
    re.IGNORECASE,
)
CONSEQUENCE = re.compile(
    r"\b(because|so|so that|otherwise|leads to|results in|means|risks?|break\w*|"
    r"fail\w*|throw\w*|leak\w*|corrupt\w*|blocker|silently|instead|without|until|"
    r"forever|stale|wrong|hide\w*|hang\w*|starve\w*|exhaust\w*|deadlock|race|"
    r"unbounded|grow\w*|cost\w*)\b",
    re.IGNORECASE,
)
# Punctuation that introduces a reason. Kept separate because a word-boundary
# assertion never matches next to a non-word character like an em dash.
CONSEQUENCE_MARK = re.compile(r"—|->|→")
# A bullet long enough to have explained itself is not a bare preference, whatever
# vocabulary it used. Cheaper and far less brittle than growing the word list.
EXPLAINED_WORDS = 25

SIMILARITY = 0.82          # near-duplicate bullet threshold
MIN_DUP_WORDS = 12         # ignore short bullets; they collide by chance


def md_files(root):
    """Every checklist file in the skill.

    README.md is not one: it is install and usage documentation for whoever sets
    the skill up, never loaded into a review's context. Holding it to the
    checklist rules would demand it be dispatched from SKILL.md and forbid it
    from naming a real repo in an example.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "scripts"}]
        for name in sorted(filenames):
            if name.endswith(".md") and name != "README.md":
                yield os.path.join(dirpath, name)


def budget_for(path):
    name = os.path.basename(path)
    return BUDGETS.get(name, BUDGETS["_default"])


def bullets(text):
    """Yield (line_no, text) for each bullet, joining wrapped continuations."""
    out = []
    cur, start = None, 0
    for n, line in enumerate(text.split("\n"), 1):
        if re.match(r"^\s*[-*]\s+\S", line):
            if cur:
                out.append((start, cur))
            cur, start = line.strip(), n
        elif cur is not None and line.startswith("  ") and line.strip():
            cur += " " + line.strip()
        elif cur:
            out.append((start, cur))
            cur = None
    if cur:
        out.append((start, cur))
    return out


def normalise(bullet):
    b = re.sub(r"`[^`]*`", " ", bullet.lower())
    b = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", b)
    b = re.sub(r"[^a-z0-9 ]", " ", b)
    return " ".join(b.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as failures")
    ap.add_argument("--stats", action="store_true",
                    help="print the budget table and exit")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    files = list(md_files(root))
    if not files:
        print(f"no markdown found under {root}", file=sys.stderr)
        return 2

    errors, warnings = [], []
    total = 0
    table = []

    for path in files:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        text = open(path, encoding="utf-8").read()
        tokens = len(text) // 4
        total += tokens
        budget = budget_for(path)
        table.append((tokens, budget, rel))

        if tokens > budget:
            errors.append(
                f"{rel}: ~{tokens} tokens over the {budget} budget. "
                f"Split it, or move rules a script can check into "
                f"scripts/scan-mechanical-rules.py.")

        # links resolve
        for target in re.findall(r"\]\(([^)#]+\.md)", text):
            if not os.path.isfile(os.path.join(os.path.dirname(path), target)):
                errors.append(f"{rel}: broken link -> {target}")

        # no project-specific identifiers
        for pattern in PROJECT_SPECIFIC:
            for m in re.finditer(pattern, text):
                line = text[:m.start()].count("\n") + 1
                errors.append(
                    f"{rel}:{line}: project-specific identifier "
                    f"{m.group(0)!r} — state the rule, not the repo.")

        # preference-only bullets
        for line_no, bullet in bullets(text):
            if not PREFERENCE_ONLY.match(bullet):
                continue
            if (CONSEQUENCE.search(bullet) or CONSEQUENCE_MARK.search(bullet)
                    or len(bullet.split()) >= EXPLAINED_WORDS):
                continue
            warnings.append(
                f"{rel}:{line_no}: preference with no consequence — "
                f"say what breaks: {bullet[:70]}...")

    if total > BUDGETS["_total"]:
        errors.append(f"whole skill ~{total} tokens over the "
                      f"{BUDGETS['_total']} total budget.")

    # every file is reachable from a sibling INDEX (or is one, or is SKILL.md)
    for path in files:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        name = os.path.basename(path)
        if name in ("INDEX.md", "SKILL.md"):
            continue
        index = os.path.join(os.path.dirname(path), "INDEX.md")
        parent_refs = ""
        if os.path.isfile(index):
            parent_refs = open(index, encoding="utf-8").read()
        else:                       # shared/ has no index; SKILL.md dispatches it
            skill = os.path.join(root, "SKILL.md")
            if os.path.isfile(skill):
                parent_refs = open(skill, encoding="utf-8").read()
        if name not in parent_refs:
            warnings.append(f"{rel}: not referenced by its INDEX.md/SKILL.md — "
                            f"a file nothing dispatches to is never read.")

    # near-duplicate bullets across files
    corpus = []
    for path in files:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        for line_no, bullet in bullets(open(path, encoding="utf-8").read()):
            norm = normalise(bullet)
            if len(norm.split()) >= MIN_DUP_WORDS:
                corpus.append((rel, line_no, norm, bullet))
    # Compare only bullets that already share most of their vocabulary; a full
    # pairwise SequenceMatcher over every bullet in the skill does not finish.
    STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "that",
            "this", "for", "on", "with", "not", "as", "be", "are", "by", "at"}
    words = [set(n.split()) - STOP for _, _, n, _ in corpus]
    index = {}
    for i, ws in enumerate(words):
        for w in ws:
            index.setdefault(w, []).append(i)

    seen = set()
    for i, (f1, l1, n1, b1) in enumerate(corpus):
        candidates = set()
        for w in words[i]:
            candidates.update(index.get(w, ()))
        for j in candidates:
            if j <= i or corpus[j][0] == f1:
                continue
            union = words[i] | words[j]
            if not union:
                continue
            if len(words[i] & words[j]) / len(union) < 0.55:
                continue
            f2, l2, n2, _ = corpus[j]
            key = (f1, l1, f2, l2)
            if key in seen:
                continue
            if difflib.SequenceMatcher(None, n1, n2).ratio() >= SIMILARITY:
                seen.add(key)
                warnings.append(
                    f"{f1}:{l1} duplicates {f2}:{l2} — keep one and link to it: "
                    f"{b1[:70]}...")

    if args.stats or "-v" in sys.argv:
        for tokens, budget, rel in sorted(table, reverse=True):
            flag = "OVER" if tokens > budget else "ok"
            print(f"{tokens:>6} / {budget:<6} {flag:<5} {rel}")
        print(f"{total:>6} total (~tokens, chars/4)")
        if args.stats:
            return 0

    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error:   {e}")

    failed = bool(errors) or (args.strict and warnings)
    print(f"\n{len(files)} files, ~{total} tokens, "
          f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
