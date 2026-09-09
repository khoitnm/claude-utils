"""Per-session token usage and estimated cost report for the current month.

Presentation only. Pricing, the billable-turn dedup rule and cost arithmetic
all live in claude_usage.py, shared with claude-session-analyze.py so the two
reports cannot drift apart.
"""

import os
import sys
from datetime import datetime

import claude_usage as cu


def collect_sessions(month, pricing):
    """Price every transcript with a record in `month`.

    Returns (records, overall) where records is a list of (Session, CostTally)
    sorted by session start. Only in-month sessions feed `overall`, so the rate
    summary it carries always reconciles with the reported total.
    """
    records = []
    overall = cu.CostTally()

    for root, _dirs, files in os.walk(cu.projects_dir()):
        for name in files:
            if not name.endswith(".jsonl"):
                continue

            try:
                session = cu.read_session(os.path.join(root, name))
            except (OSError, ValueError):
                continue  # unreadable or malformed transcripts are skipped

            if month not in session.months:
                continue

            tally = cu.CostTally()
            for turn in session.turns:
                tally.add_turn(turn, pricing)

            overall.merge(tally)
            records.append((session, tally))

    records.sort(key=lambda item: item[0].start or "")
    return records, overall


def print_session_table(records, enterprise_discount):
    # Widths hold the largest realistic values, so rows stay aligned with the
    # header and with each other.
    header = ("{:<38} | {:<19} | {:<19} | {:<10} | {:<40} | {:<12} | {:<12} | "
              "{:<15} | {:<13}").format(
        "Session Hash / ID", "Start Date", "End Date", "Cost", "Summary",
        "Input Tok", "Output Tok", "Cache R", "Cache W")
    if enterprise_discount is not None:
        header += " | {:<11}".format("Cost (Ent)")

    border_line = "-" * len(header)
    print(border_line)
    print(header)
    print(border_line)

    for session, tally in records:
        row = ("{:<38} | {:<19} | {:<19} | {:<10} | {:<40} | {:<12,d} | {:<12,d} | "
               "{:<15,d} | {:<13,d}").format(
            session.session_id,
            session.start or "N/A",
            session.end or "N/A",
            "${:.4f}".format(tally.cost),
            cu.clean_summary_text(session.summary, max_len=40),
            tally.tokens["input"],
            tally.tokens["output"],
            tally.tokens["cache_read"],
            tally.cache_write)
        if enterprise_discount is not None:
            row += " | {:<11}".format(
                "${:.4f}".format(cu.discounted(tally.cost, enterprise_discount)))
        print(row)

    print(border_line)


def get_claude_session_details():
    if not os.path.exists(cu.projects_dir()):
        print("Directory not found: {}. Ensure Claude Code has been initialized.".format(
            cu.projects_dir()))
        return 1

    pricing, pricing_source = cu.load_pricing()
    enterprise_discount = cu.load_enterprise_discount()

    month = datetime.now().strftime("%Y-%m")
    records, overall = collect_sessions(month, pricing)

    report_start = min((s.start for s, _ in records if s.start), default=None)
    report_end = max((s.end for s, _ in records if s.end), default=None)

    print("\nClaude Code Session Usage Report ({})".format(month))
    print("Report Start Date:         {}".format(report_start or "N/A"))
    print("Report End Date:           {}".format(report_end or "N/A"))
    cu.print_pricing_provenance(pricing_source, enterprise_discount)

    print_session_table(records, enterprise_discount)

    print("Total Sessions This Month: {}".format(len(records)))
    print("Total Token Usage:         Input: {:,d} | Output: {:,d} | Cache Read: {:,d} | "
          "Cache Write: {:,d}".format(
              overall.tokens["input"], overall.tokens["output"],
              overall.tokens["cache_read"], overall.cache_write))
    print("Total Estimated Cost:      ${:.4f}".format(overall.cost))
    if enterprise_discount is not None:
        print("Total Cost (Enterprise):   ${:.4f}".format(
            cu.discounted(overall.cost, enterprise_discount)))

    if overall.rates_used:
        print("\nPricing Table Used (USD per million tokens)")
        for line in cu.build_rates_table(overall.rates_used, enterprise_discount):
            print(line)

    cu.print_enterprise_footnote(enterprise_discount)
    print()
    return 0


if __name__ == "__main__":
    cu.configure_stdout()
    sys.exit(get_claude_session_details())
