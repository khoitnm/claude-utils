"""Cost analysis for a single Claude Code session transcript.

Presentation only. Pricing, the billable-turn dedup rule and cost arithmetic
all live in claude_usage.py, shared with claude-sessions-usage.py so the two
reports cannot drift apart; the conclusions and the carry-cost attribution
behind them live in session_insights.py. This file lays out what those two
produce and nothing else.

The report leads with ranked findings because the per-step table alone cannot
answer the question it invites. A table prices a turn by what it spent when it
ran; the findings price it by what it added to the context and how many turns
then had to re-read it, which is where a long session's money actually goes.
"""

import sys
from pathlib import Path

import claude_usage as cu
import session_insights as si

# Tools whose most useful detail is a path or a pattern rather than a command.
PATH_TOOLS = ("Read", "View", "Write", "Edit", "Grep", "Glob")

ACTION_MAX_LEN = 74
CAUSE_MAX_LEN = 62

# A step that added more than this is called out in the table, replacing the
# old absolute cache-read flag: on a long session that flag fired on nearly
# every row, and a warning that is always on carries no information.
SPIKE_TOKENS = 4_000


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


def clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit - 2] + ".."


def find_transcript(session_uuid):
    projects = Path(cu.projects_dir())
    matches = sorted(projects.glob("**/{}.jsonl".format(session_uuid)))
    return matches[0] if matches else None


def format_duration(seconds):
    if seconds is None:
        return "N/A"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return "{}h {:02d}m".format(hours, minutes) if hours else "{}m".format(minutes)


def print_headline(insights, enterprise_discount):
    """The handful of numbers that frame everything below."""
    tally = insights.tally
    session = insights.session
    steps = insights.steps
    context = steps[-1].context if steps else 0

    print("Session Window:            {} -> {}  ({})".format(
        session.start or "N/A", session.end or "N/A",
        format_duration(insights.span_seconds)))
    print("Shape:                     {} turns from {} prompts ({:.1f} turns per "
          "prompt), {} tool calls".format(
              tally.turns, session.prompts or "?",
              float(tally.turns) / session.prompts if session.prompts else 0.0,
              sum(len(s.turn.tool_results) for s in steps)))
    print("Context:                   {:,} tok at turn 1 -> {:,} tok at turn {}"
          " ({:.1f}x)".format(
              insights.preamble_tokens, context, tally.turns,
              float(context) / insights.preamble_tokens
              if insights.preamble_tokens else 0.0))
    print("Cost:                      ${:.4f} total, ${:.4f} per turn average".format(
        tally.cost, tally.cost / tally.turns if tally.turns else 0.0))
    if enterprise_discount is not None:
        print("Cost (Enterprise):         ${:.4f}".format(
            cu.discounted(tally.cost, enterprise_discount)))


def print_findings(insights):
    """The ranked conclusions, most money first."""
    conclusions = si.findings(insights)

    print("\n" + "=" * 100)
    print("FINDINGS  (ranked by dollars at stake)")
    print("=" * 100)

    if not conclusions:
        print("\nToo little in this session to draw conclusions from.")
        return

    for number, finding in enumerate(conclusions, start=1):
        print("\n{}. [{:>8}] {}".format(number, "${:,.2f}".format(finding.impact),
                                        finding.title))
        for line in finding.detail:
            print("      {}".format(line))
        if finding.advice:
            print("      -> {}".format(finding.advice))

    attributed = (sum(s.carry_cost + s.rewrite_cost for s in insights.steps)
                  + sum(b.cost for b in insights.bases))
    prompt_cost = insights.tally.cost - insights.tally.cost_by_component["output"]

    print("\n" + "-" * 100)
    print("Carry cost = tokens a step added x (one cache write + a cache read on every")
    print("remaining turn, up to the next compaction). Counts marked ~ are estimated")
    print("from transcript text at {:.0f} chars per token; every figure in the ledger".format(
        si.CHARS_PER_TOKEN))
    print("tables below is exact.")
    print("Attribution accounts for ${:,.2f} of the ${:,.2f} actually billed for prompt "
          "tokens ({:+.0f}%).".format(
              attributed, prompt_cost,
              100.0 * (attributed / prompt_cost - 1.0) if prompt_cost else 0.0))
    print("Any residual is cache-boundary rounding: prefix growth and billed cache")
    print("writes do not line up token for token. Read findings as proportions, not cents.")
    print("-" * 100)


def print_cost_split(insights):
    """The exact ledger split, which every estimate above is anchored to."""
    total = insights.tally.cost
    rows = []
    for component, title in cu.RATE_COMPONENTS:
        cost = insights.tally.cost_by_component[component]
        if not cost:
            continue
        rows.append([
            title,
            "{:,d}".format(insights.tally.tokens[component]),
            "${:,.4f}".format(cost),
            "{:.1f}%".format(100.0 * cost / total) if total else "n/a",
        ])
    print("\nWhere The Money Went (exact, from the ledger)")
    for line in cu.render_table(
            ["Token Component", "Tokens", "Cost", "Share"], rows,
            right_align=(1, 2, 3)):
        print(line)


def print_growth_split(insights):
    """The four things that grew the context, and what carrying each cost."""
    rows = [
        [bucket.label,
         "{:,d}".format(bucket.calls),
         "~{:,d}".format(bucket.tokens),
         "${:,.4f}".format(bucket.carry_cost),
         "{:.1f}%".format(100.0 * bucket.share)]
        for bucket in insights.category_payload
    ]
    if not rows:
        return
    print("\nWhat Grew The Context (estimated, ranked by carry cost)")
    for line in cu.render_table(
            ["Source", "Blocks", "Tokens", "Carry Cost", "Share"], rows,
            right_align=(1, 2, 3, 4)):
        print(line)


def print_skill_split(insights):
    """Cost per driving skill, where the transcript attributes one."""
    if len(insights.skill_costs) < 2:
        return
    rows = [
        [label, "{:,d}".format(turns), "${:,.4f}".format(cost),
         "${:,.4f}".format(cost / turns) if turns else "n/a",
         "{:,d}".format(output)]
        for label, turns, cost, output in insights.skill_costs
    ]
    print("\nCost By Driving Skill")
    for line in cu.render_table(
            ["Skill", "Turns", "Cost", "Cost/Turn", "Output Tok"], rows,
            right_align=(1, 2, 3, 4)):
        print(line)


def print_step_table(insights):
    """The full per-step ledger, now carrying the two columns that explain it.

    Every step is listed. The table is the audit trail for the findings, so
    dropping rows from it would leave nothing to check them against.
    """
    rows = []
    for step in insights.steps:
        tokens = step.priced.tokens
        flag = " (!)" if step.caused >= SPIKE_TOKENS else ""
        if step.rewrite_tokens >= si.REWRITE_TOKENS:
            flag += " (CACHE RE-WRITE +${:,.2f})".format(step.rewrite_cost)
        rows.append([
            str(step.index),
            step.priced.label,
            "{:,d}".format(step.context),
            "{:+,d}".format(step.growth) if step.index > 1 else "base",
            "{:,d}".format(tokens["cache_read"]),
            "{:,d}".format(cu.cache_write_of(tokens)),
            "{:,d}".format(tokens["input"]),
            "{:,d}".format(tokens["output"]),
            "${:,.4f}".format(step.priced.cost),
            "${:,.4f}".format(step.carry_cost),
            clip(step.cause, CAUSE_MAX_LEN) + flag,
            clip(describe_action(step.turn), ACTION_MAX_LEN),
        ])

    headers = ["Step", "Model", "Context", "Growth", "Cache Read", "Cache Write",
               "Input", "Output", "Cost", "Carry", "Why Context Grew",
               "Assistant Action / Response Detail"]

    print("\nPer-Step Ledger")
    print("  Context    = prompt tokens this turn carried")
    print("  Growth     = change in context since the previous turn")
    print("  Cost       = what this turn itself was billed")
    print("  Carry      = total cost of what this turn added, across every later turn")
    print("  (!)        = added {:,}+ tokens the rest of the session had to re-read".format(
        SPIKE_TOKENS))
    print("  CACHE RE-WRITE = billed a cache write far larger than the context grew,")
    print("               meaning the prompt cache had expired and the whole prefix")
    print("               was written again")
    for line in cu.render_table(headers, rows,
                                right_align=(0, 2, 3, 4, 5, 6, 7, 8, 9)):
        print(line)


def analyze_session_totals(session_uuid):
    target_file = find_transcript(session_uuid)
    if target_file is None:
        print("[ERROR] Session file for UUID '{}' not found under {}".format(
            session_uuid, cu.projects_dir()), file=sys.stderr)
        return 1

    pricing, pricing_source = cu.load_pricing()
    enterprise_discount = cu.load_enterprise_discount()

    session = cu.read_session(str(target_file), with_blocks=True, with_details=True)
    if not session.turns:
        print("[ERROR] No token usage found in {}".format(target_file), file=sys.stderr)
        return 1

    insights = si.analyze(session, pricing)

    print("\nAnalyzing Session: {}".format(target_file.name))
    print_headline(insights, enterprise_discount)
    cu.print_pricing_provenance(pricing_source, enterprise_discount)

    print_findings(insights)
    print_cost_split(insights)
    print_growth_split(insights)
    print_skill_split(insights)
    print_step_table(insights)

    tally = insights.tally
    print("\nAggregated Totals Across {} Logical Steps:".format(tally.turns))
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

    session_uuid = sys.argv[1]
    filename = "session-analyze_{}.txt".format(cu.safe_name_part(session_uuid))

    with cu.report_to_file("session-analyze", filename) as report_path:
        status = analyze_session_totals(session_uuid)

    cu.announce_report(report_path)
    sys.exit(status)
