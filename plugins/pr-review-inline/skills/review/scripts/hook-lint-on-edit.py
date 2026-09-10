#!/usr/bin/env python3
"""PostToolUse hook: lint the pr-review-inline checklists after they are edited.

Reads the hook JSON on stdin. If the edited file is not inside this skill, exits
0 without a word. Otherwise runs lint-skill-docs.py from the skill root and:

  linter exit 0, no warnings  -> exit 0, silent
  linter exit 0, warnings     -> exit 0, warnings fed back as context
  linter exit non-zero        -> exit 2, output fed back to Claude as a blocker

Exit 2 is what makes the mistake visible in the turn that caused it, which is
the whole point of hooking the edit rather than the commit.
"""

import json
import os
import subprocess
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINTER = os.path.join(SKILL_ROOT, "scripts", "lint-skill-docs.py")


def edited_path(payload):
    response = payload.get("tool_response") or {}
    tool_input = payload.get("tool_input") or {}
    return (response.get("filePath") or tool_input.get("file_path") or "")


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                      # not our problem; never break the turn

    path = edited_path(payload)
    if not path:
        return 0

    try:
        inside = os.path.commonpath(
            [os.path.abspath(path), SKILL_ROOT]) == SKILL_ROOT
    except ValueError:                # different drives on Windows
        return 0
    if not inside or not os.path.isfile(LINTER):
        return 0

    run = subprocess.run([sys.executable, LINTER], cwd=SKILL_ROOT,
                         capture_output=True, text=True)
    output = (run.stdout + run.stderr).strip()

    if run.returncode != 0:
        print(f"pr-review-inline checklist lint failed:\n{output}",
              file=sys.stderr)
        return 2                      # blocking: fed back to Claude

    if "warning:" in output:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext":
                    f"pr-review-inline checklist lint warnings:\n{output}",
            },
            "suppressOutput": True,
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
