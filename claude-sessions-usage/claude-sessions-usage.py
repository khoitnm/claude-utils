"""Per-session token usage and estimated cost report for the current month.

Presentation only. Pricing, the billable-turn dedup rule and cost arithmetic
all live in claude_usage.py, shared with claude-session-analyze.py so the two
reports cannot drift apart.
"""

import os
import sys
from datetime import datetime

import claude_usage as cu

SUMMARY_MAX_LEN = 250


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


def session_ledger(records, enterprise_discount):
    """The per-session table as CSV headers and rows.

    Unformatted on purpose - raw integers and floats, no thousands separators
    and no dollar signs - so a spreadsheet can sort and filter it. The summary
    is the one clipped field: SUMMARY_MAX_LEN keeps a runaway first prompt from
    dwarfing every other column when the file is opened.
    """
    headers = ["session_id", "start", "end", "cost"]
    if enterprise_discount is not None:
        headers.append("cost_ent")
    headers.extend(["input", "output", "cache_read", "cache_write", "summary"])

    rows = []
    for session, tally in records:
        row = [
            session.session_id,
            session.start or "",
            session.end or "",
            round(tally.cost, 6),
        ]
        if enterprise_discount is not None:
            row.append(round(cu.discounted(tally.cost, enterprise_discount), 6))
        row.extend([
            tally.tokens["input"],
            tally.tokens["output"],
            tally.tokens["cache_read"],
            tally.cache_write,
            cu.clean_summary_text(session.summary, max_len=SUMMARY_MAX_LEN),
        ])
        rows.append(row)
    return headers, rows


def print_table_pointer(csv_path, rows, enterprise_discount):
    """Where the per-session table went, and what is in it.

    The table itself is too wide to print: a summary worth reading does not fit
    a fixed-width column, so the rows go to a CSV and the report keeps the
    totals.
    """
    print("\nPer-Session Table")
    if not csv_path:
        print("  Not saved: the run has no report folder to write it into.")
        return
    print("  {:,} rows, one per session -> {}".format(
        rows, os.path.basename(csv_path)))
    if enterprise_discount is not None:
        print("  cost/cost_ent       billed cost, and the same after the "
              "enterprise discount")
    else:
        print("  cost                billed cost for the session")
    print("  input/output        tokens billed at the full rate")
    print("  cache_read/_write   tokens billed at the cache rates")
    print("  summary             first {} characters of the session summary".format(
        SUMMARY_MAX_LEN))


def get_claude_session_details(report_path):
    if not os.path.exists(cu.projects_dir()):
        print("Directory not found: {}. Ensure Claude Code has been initialized.".format(
            cu.projects_dir()))
        return 1, None

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

    headers, rows = session_ledger(records, enterprise_discount)
    csv_path = cu.write_csv(
        cu.side_file(report_path, "{}_sessions.csv".format(
            os.path.splitext(os.path.basename(report_path))[0]
            if report_path else "sessions-usage")),
        headers, rows)
    print_table_pointer(csv_path, len(rows), enterprise_discount)

    print("\nTotal Sessions This Month: {}".format(len(records)))
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
    return 0, csv_path


if __name__ == "__main__":
    cu.configure_stdout()

    with cu.report_to_file("sessions-usage", "sessions-usage.txt") as report_path:
        status, table_path = get_claude_session_details(report_path)

    cu.announce_report(report_path, table_path)
    sys.exit(status)
