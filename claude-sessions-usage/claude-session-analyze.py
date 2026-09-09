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

The full per-turn ledger is written to a CSV beside the report rather than
printed. On a long session it is hundreds of rows a reader scrolls past to
reach the conclusions, and it is the one part of the report a spreadsheet
handles better than a fixed-width table. What stays on the page is the part a
reader can act on: the steps worth fixing, and the points the session could
have been split at.
"""

import sys
from pathlib import Path

import claude_usage as cu
import session_insights as si

# Tools whose most useful detail is a path or a pattern rather than a command.
PATH_TOOLS = ("Read", "View", "Write", "Edit", "Grep", "Glob")

ACTION_MAX_LEN = 74
CAUSE_MAX_LEN = 62

# How many rows the printed shortlists carry before they stop being shortlists.
FIX_ROWS = 15
CUT_ROWS = 12


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
    print("from transcript text at {:.0f} chars per token, and are the only estimated".format(
        si.CHARS_PER_TOKEN))
    print("numbers here; everything else, the ledger CSV included, is derived from")
    print("billed token counts.")
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


def print_fix_list(insights):
    """The steps worth changing, each tagged with the change that applies.

    Ranked by carry cost, because that is what a step actually cost the
    session, and filtered to steps where something could have been done
    differently: a row with no lever is a turn that simply did its work.
    """
    tagged = [s for s in insights.steps if insights.levers.get(s.index)]
    if not tagged:
        return
    ranked = sorted(tagged, key=lambda s: -s.carry_cost)[:FIX_ROWS]

    rows = []
    for step in ranked:
        reach = insights.reaches[step.index - 1].earliest
        rows.append([
            str(step.index),
            insights.levers[step.index],
            "${:,.4f}".format(step.carry_cost),
            "+{:,d}".format(step.caused),
            "{}x".format(step.remaining),
            str(reach) if reach else "-",
            clip(step.cause, CAUSE_MAX_LEN),
        ])

    print("\nSteps Worth Fixing (ranked by carry cost, {} of {} tagged steps)".format(
        len(rows), len(tagged)))
    print("  Lever   = the cheapest thing that would have changed this step's cost")
    print("  Added   = tokens this step handed to the rest of the session")
    print("  Re-read = how many later turns then carried them")
    print("  Reach   = earliest step this one re-opened a file from ('-' = new ground),")
    print("            which is how far back the history it still needed reached")
    for line in cu.render_table(
            ["Step", "Lever", "Carry", "Added", "Re-read", "Reach",
             "Why Context Grew"], rows, right_align=(0, 2, 3, 4, 5)):
        print(line)

    used = [(tag, hint) for tag, hint in si.LEVER_HINTS
            if any(row[1] == tag for row in rows)]
    for tag, hint in used:
        print("  {:<8} {}".format(tag, hint))


def print_cut_points(insights):
    """Where the session could have been split, priced against what that costs.

    This is the table that settles what the reset ceiling can only raise. A
    saving from dropping history is not free: whatever the later work went back
    to has to be re-read into the new session and carried again. Both sides are
    priced here, so the decision is a subtraction rather than a judgement.
    """
    if not insights.cuts:
        return
    ranked = sorted(insights.cuts, key=lambda c: -c.net)[:CUT_ROWS]

    rows = [[
        str(cut.index),
        "${:,.4f}".format(cut.net),
        "${:,.4f}".format(cut.savings),
        "{:,d}".format(cut.dropped),
        "${:,.4f}".format(cut.reentry_cost),
        "{} / ~{:,} tok".format(cut.revisited, cut.reentry_tokens),
        clip(cut.label, 46),
    ] for cut in ranked]

    worth = [c for c in insights.cuts if c.net > 0]
    print("\nWhere The Session Could Have Been Split ({} of {} prompt boundaries"
          " were worth taking)".format(len(worth), len(insights.cuts)))
    print("  Only turns answering a new prompt are listed: splitting anywhere else")
    print("  would cut a turn off from the tool output it was reacting to.")
    print("  Saves     = what no longer carrying the history left behind is worth")
    print("  Puts back = the files the later work went back to across the split, which")
    print("              a new session has to re-read and then carry again")
    print("  Net       = the first less the second, and the figure to act on. Files are")
    print("              the only dependency a transcript records, so reasoning carried")
    print("              in the conversation is not counted on either side, and a file")
    print("              seen only inside a shell command has no size to put back.")
    for line in cu.render_table(
            ["Step", "Net", "Saves", "Drops Tok", "Puts Back", "Files Revisited",
             "The Prompt It Answers"],
            rows, right_align=(0, 1, 2, 3, 4, 5)):
        print(line)



def step_ledger(insights):
    """The full per-turn ledger as CSV headers and rows.

    Unformatted on purpose - raw integers and floats, no truncation - so the
    file can be sorted and filtered rather than read. The printed tables are
    the formatted view of the same numbers.
    """
    headers = ["step", "model", "timestamp", "gap_seconds", "starts_prompt",
               "skill", "lever", "context", "growth", "added", "reread_by",
               "reach_back", "cache_read", "cache_write", "input", "output",
               "cost", "carry_cost", "rewrite_tokens", "rewrite_cost",
               "why_context_grew", "assistant_action"]
    rows = []
    for step in insights.steps:
        tokens = step.priced.tokens
        rows.append([
            step.index,
            step.priced.label,
            step.turn.timestamp or "",
            "" if step.gap_seconds is None else step.gap_seconds,
            int(bool(step.turn.starts_prompt)),
            step.turn.skill or "",
            insights.levers.get(step.index, ""),
            step.context,
            step.growth,
            step.caused,
            step.remaining,
            insights.reaches[step.index - 1].earliest or "",
            tokens["cache_read"],
            cu.cache_write_of(tokens),
            tokens["input"],
            tokens["output"],
            round(step.priced.cost, 6),
            round(step.carry_cost, 6),
            step.rewrite_tokens,
            round(step.rewrite_cost, 6),
            step.cause,
            describe_action(step.turn),
        ])
    return headers, rows


def print_ledger_pointer(csv_path, rows):
    """Where the ledger went, and what is in it."""
    print("\nPer-Step Ledger")
    if not csv_path:
        print("  Not saved: the run has no report folder to write it into.")
        return
    print("  {:,} rows, one per assistant turn -> {}".format(
        rows, Path(csv_path).name))
    print("  context/growth      what this turn carried, and how much of it was new")
    print("  added/reread_by     what it handed forward, and how many turns re-read it")
    print("  cost/carry_cost     what the turn was billed, and what its addition cost")
    print("                      in total across every later turn")
    print("  reach_back          earliest step this turn re-opened a file from")
    print("  lever               the cheapest thing that would have changed its cost")
    print("  rewrite_tokens      cache write beyond what the context grew: an expired")
    print("                      cache re-writing the whole prefix")


def analyze_session_totals(session_uuid, report_path=None):
    target_file = find_transcript(session_uuid)
    if target_file is None:
        print("[ERROR] Session file for UUID '{}' not found under {}".format(
            session_uuid, cu.projects_dir()), file=sys.stderr)
        return 1, None

    pricing, pricing_source = cu.load_pricing()
    enterprise_discount = cu.load_enterprise_discount()

    session = cu.read_session(str(target_file), with_blocks=True, with_details=True)
    if not session.turns:
        print("[ERROR] No token usage found in {}".format(target_file), file=sys.stderr)
        return 1, None

    insights = si.analyze(session, pricing)

    print("\nAnalyzing Session: {}".format(target_file.name))
    print_headline(insights, enterprise_discount)
    cu.print_pricing_provenance(pricing_source, enterprise_discount)

    print_findings(insights)
    print_cost_split(insights)
    print_growth_split(insights)
    print_skill_split(insights)
    print_fix_list(insights)
    print_cut_points(insights)

    headers, rows = step_ledger(insights)
    csv_path = cu.write_csv(
        cu.side_file(report_path, "{}_steps.csv".format(
            Path(report_path).stem if report_path else "session")),
        headers, rows)
    print_ledger_pointer(csv_path, len(rows))

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
    return 0, csv_path


if __name__ == "__main__":
    cu.configure_stdout()

    if len(sys.argv) != 2:
        print("Usage: python claude-session-analyze.py <session-uuid>", file=sys.stderr)
        sys.exit(2)

    session_uuid = sys.argv[1]
    filename = "session-analyze_{}.txt".format(cu.safe_name_part(session_uuid))

    with cu.report_to_file("session-analyze", filename) as report_path:
        status, ledger_path = analyze_session_totals(session_uuid, report_path)

    cu.announce_report(report_path, ledger_path)
    sys.exit(status)
