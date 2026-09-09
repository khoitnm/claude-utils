"""Per-step cost breakdown for a single Claude Code session transcript.

Presentation only. Pricing, the billable-turn dedup rule and cost arithmetic
all live in claude_usage.py, shared with claude-sessions-usage.py so the two
reports cannot drift apart.
"""

import sys
from pathlib import Path

import claude_usage as cu

# Cache reads above this in a single response are worth flagging: they usually
# mean the whole context is being re-read every turn.
CACHE_READ_WARN_THRESHOLD = 100_000

# Tools whose most useful detail is a path or a pattern rather than a command.
PATH_TOOLS = ("Read", "View", "Write", "Edit", "Grep", "Glob")

ACTION_MAX_LEN = 117


def describe_action(turn):
    """Summarize what the assistant did in one turn, across all its blocks."""
    parts = []
    for block in turn.blocks:
        block_type = block.get("type")
        if block_type == "text":
            text = " ".join(block.get("text", "").split())
            if text:
                parts.append(text[:120])
        elif block_type == "tool_use":
            name = block.get("name", "unknown")
            tool_input = block.get("input") or {}
            detail = ""
            if isinstance(tool_input, dict):
                if name == "Bash":
                    detail = tool_input.get("command", "")
                elif name in PATH_TOOLS:
                    detail = tool_input.get("file_path") or tool_input.get("pattern") or ""
            detail = " ".join(str(detail).split())[:50]
            parts.append("[Tool: {}({})]".format(name, detail) if detail
                         else "[Tool: {}]".format(name))

    if parts:
        return " | ".join(parts)
    return "User: {}".format(turn.user_context[:80])


def find_transcript(session_uuid):
    projects = Path(cu.projects_dir())
    matches = sorted(projects.glob("**/{}.jsonl".format(session_uuid)))
    return matches[0] if matches else None


def analyze_session_totals(session_uuid):
    target_file = find_transcript(session_uuid)
    if target_file is None:
        print("[ERROR] Session file for UUID '{}' not found under {}".format(
            session_uuid, cu.projects_dir()), file=sys.stderr)
        return 1

    pricing, pricing_source = cu.load_pricing()
    enterprise_discount = cu.load_enterprise_discount()

    session = cu.read_session(str(target_file), with_blocks=True)
    if not session.turns:
        print("[ERROR] No token usage found in {}".format(target_file), file=sys.stderr)
        return 1

    tally = cu.CostTally()
    rows = []

    for index, turn in enumerate(session.turns, start=1):
        priced = tally.add_turn(turn, pricing)

        action = describe_action(turn)
        if len(action) > ACTION_MAX_LEN:
            action = action[:ACTION_MAX_LEN - 2] + ".."
        if priced.tokens["cache_read"] > CACHE_READ_WARN_THRESHOLD:
            action += " (!)"

        rows.append([
            str(index),
            priced.label,
            "{:,d}".format(priced.tokens["cache_read"]),
            "{:,d}".format(cu.cache_write_of(priced.tokens)),
            "{:,d}".format(priced.tokens["input"]),
            "{:,d}".format(priced.tokens["output"]),
            "${:,.4f}".format(priced.cost),
            action,
        ])

    headers = ["Step", "Model", "Cache Read", "Cache Write", "Input", "Output", "Cost",
               "Assistant Action / Response Detail"]

    print("\nAnalyzing Session: {}".format(target_file.name))
    print("Session Window:            {} -> {}".format(
        session.start or "N/A", session.end or "N/A"))
    cu.print_pricing_provenance(pricing_source, enterprise_discount)

    for line in cu.render_table(headers, rows, right_align=(0, 2, 3, 4, 5, 6)):
        print(line)

    print("Aggregated Totals Across {} Logical Steps:".format(tally.turns))
    print("  - Total Input Tokens:        {:,}".format(tally.tokens["input"]))
    print("  - Total Output Tokens:       {:,}".format(tally.tokens["output"]))
    print("  - Total Cache Read Tokens:   {:,}".format(tally.tokens["cache_read"]))
    print("  - Total Cache Write Tokens:  {:,}".format(tally.cache_write))
    print("  - Estimated Total Cost:      ${:.4f}".format(tally.cost))
    if enterprise_discount is not None:
        print("  - Cost (Enterprise):         ${:.4f}".format(
            cu.discounted(tally.cost, enterprise_discount)))

    print("\nPricing Table Used (USD per million tokens)")
    for line in cu.build_rates_table(tally.rates_used, enterprise_discount):
        print(line)

    cu.print_enterprise_footnote(enterprise_discount)
    print()
    return 0


if __name__ == "__main__":
    cu.configure_stdout()

    if len(sys.argv) != 2:
        print("Usage: python claude-session-analyze.py <session-uuid>", file=sys.stderr)
        sys.exit(2)

    sys.exit(analyze_session_totals(sys.argv[1]))
