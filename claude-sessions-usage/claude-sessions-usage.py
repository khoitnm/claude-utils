import os
import re
import sys
import json
import time
import urllib.error
import urllib.request
from datetime import datetime

# Live pricing is published as markdown on the Claude docs site. There is no
# machine-readable pricing endpoint (the Models API returns capabilities, not
# prices), so this page is the closest thing to an authoritative source.
PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
PRICING_CACHE = os.path.join(
    os.path.expanduser("~"), ".cache", "claude-sessions-usage", "pricing.json"
)
PRICING_CACHE_TTL = 24 * 60 * 60
FETCH_TIMEOUT = 10

# Anthropic does not publish per-token Enterprise rates - they are negotiated
# case by case - so an Enterprise column can only be produced from a discount
# the operator supplies. Percent off list ("30") or a fraction ("0.30").
ENTERPRISE_DISCOUNT_ENV = "CLAUDE_ENTERPRISE_DISCOUNT"

# Fallback rates in USD per million tokens, used only when the live lookup and
# the on-disk cache both fail. Snapshot taken 2026-09-08.
FALLBACK_RATES_ASOF = "2026-09-08"


def _rates(base_input, write_5m, write_1h, cache_read, output):
    return {
        "input": base_input,
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
        "cache_read": cache_read,
        "output": output,
    }


FALLBACK_PRICING = {
    ("fable", (5, 1)): _rates(10.00, 12.50, 20.00, 0.25, 50.00),
    ("fable", (5,)): _rates(10.00, 12.50, 20.00, 1.00, 50.00),
    ("mythos", (5, 1)): _rates(10.00, 12.50, 20.00, 0.25, 50.00),
    ("mythos", (5,)): _rates(10.00, 12.50, 20.00, 1.00, 50.00),
    ("sonnet", (5,)): _rates(2.00, 2.50, 4.00, 0.20, 10.00),
    ("sonnet", (4, 6)): _rates(3.00, 3.75, 6.00, 0.30, 15.00),
    ("sonnet", (4, 5)): _rates(3.00, 3.75, 6.00, 0.30, 15.00),
    ("haiku", (4, 5)): _rates(1.00, 1.25, 2.00, 0.10, 5.00),
}
for _opus_version in [(5,), (4, 8), (4, 7), (4, 6), (4, 5)]:
    FALLBACK_PRICING[("opus", _opus_version)] = _rates(5.00, 6.25, 10.00, 0.50, 25.00)

# Applied when a model name matches no known family at all.
DEFAULT_RATES = _rates(2.00, 2.50, 4.00, 0.20, 10.00)

MODEL_FAMILIES = ("fable", "mythos", "opus", "sonnet", "haiku")

RATE_COMPONENTS = [
    ("input", "Input"),
    ("cache_write_5m", "5m Cache Write"),
    ("cache_write_1h", "1h Cache Write"),
    ("cache_read", "Cache Read"),
    ("output", "Output"),
]


def parse_model_key(text):
    """Reduce a model name or API id to a (family, version) key.

    Handles both docs table names ("Claude Opus 4.1 ([retired](...))") and
    transcript model ids ("claude-haiku-4-5-20251001", "claude-opus-5").
    """
    if not text:
        return None

    normalized = text.lower()
    normalized = re.sub(r"[-@]20\d{6}\b", "", normalized)  # dated snapshots
    normalized = normalized.replace("[1m]", "")            # context-window suffix

    family = next((f for f in MODEL_FAMILIES if f in normalized), None)
    if not family:
        return None

    before, _, after = normalized.partition(family)

    # Current naming puts the version after the family (opus 4.8); Claude 3.x
    # put it before (claude-3-5-sonnet).
    match = re.match(r"[\s\-]*((?:\d+[.\-])*\d+)", after)
    if not match:
        match = re.search(r"((?:\d+[.\-])*\d+)[\s\-]*$", before)
    if not match:
        return family, ()

    return family, tuple(int(part) for part in re.split(r"[.\-]", match.group(1)))


def parse_pricing_markdown(markdown):
    """Extract the model pricing table from the docs page markdown."""
    section = markdown.split("## Model pricing", 1)
    if len(section) < 2:
        return {}
    body = re.split(r"\n## ", section[1], maxsplit=1)[0]

    columns = None
    rates = {}

    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]

        # Locate the columns by keyword rather than position, so an added or
        # reordered column doesn't silently shift the rates.
        if columns is None:
            lowered = [cell.lower() for cell in cells]
            wanted = {
                "input": "base input",
                "cache_write_5m": "5m cache",
                "cache_write_1h": "1h cache",
                "cache_read": "cache hit",
                "output": "output",
            }
            found = {}
            for field, needle in wanted.items():
                index = next((i for i, cell in enumerate(lowered) if needle in cell), None)
                if index is None:
                    break
                found[field] = index
            else:
                columns = found
            continue

        key = parse_model_key(cells[0])
        if not key:
            continue

        parsed = {}
        for field, index in columns.items():
            if index >= len(cells):
                break
            # Trailing footnote markers ("$0.25 / MTok1") are ignored.
            price = re.search(r"\$([\d.]+)", cells[index])
            if not price:
                break
            parsed[field] = float(price.group(1))
        else:
            rates[key] = parsed

    return rates


def serialize_rates(rates):
    return {
        "{}:{}".format(family, ".".join(str(v) for v in version)): values
        for (family, version), values in rates.items()
    }


def deserialize_rates(raw):
    rates = {}
    for key, values in raw.items():
        family, _, version = key.partition(":")
        parsed_version = tuple(int(v) for v in version.split(".") if v)
        rates[(family, parsed_version)] = values
    return rates


def read_cached_pricing():
    try:
        with open(PRICING_CACHE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        rates = deserialize_rates(cached["rates"])
        if not rates:
            return None
        return rates, cached.get("fetched_at", "unknown"), cached.get("cached_at", 0)
    except (OSError, ValueError, KeyError):
        return None


def write_cached_pricing(rates, fetched_at):
    try:
        os.makedirs(os.path.dirname(PRICING_CACHE), exist_ok=True)
        with open(PRICING_CACHE, "w", encoding="utf-8") as f:
            json.dump({
                "source_url": PRICING_URL,
                "fetched_at": fetched_at,
                "cached_at": time.time(),
                "rates": serialize_rates(rates),
            }, f, indent=2)
    except OSError:
        pass  # A read-only cache location is not worth failing the report over.


def load_pricing():
    """Return (rates, source_description).

    Order of preference: fresh cache, live fetch, stale cache, bundled fallback.
    """
    cached = read_cached_pricing()
    if cached and (time.time() - cached[2]) < PRICING_CACHE_TTL:
        return cached[0], f"cached from docs (fetched {cached[1]})"

    try:
        request = urllib.request.Request(
            PRICING_URL, headers={"User-Agent": "claude-sessions-usage"}
        )
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            markdown = response.read().decode("utf-8", errors="replace")
        rates = parse_pricing_markdown(markdown)
        if rates:
            fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            write_cached_pricing(rates, fetched_at)
            return rates, f"live from {PRICING_URL} (fetched {fetched_at})"
        reason = "pricing table not found in page"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = f"{type(exc).__name__}: {exc}"

    if cached:
        return cached[0], f"stale cache (fetched {cached[1]}); live lookup failed - {reason}"

    return FALLBACK_PRICING, (
        f"built-in fallback rates as of {FALLBACK_RATES_ASOF}; "
        f"live lookup failed - {reason}"
    )


def load_enterprise_discount():
    """Read the operator-supplied Enterprise discount, or None if unset."""
    raw = os.environ.get(ENTERPRISE_DISCOUNT_ENV, "").strip()
    if not raw:
        return None

    try:
        value = float(raw.rstrip("%").strip())
    except ValueError:
        print(f"Ignoring {ENTERPRISE_DISCOUNT_ENV}={raw!r}: not a number", file=sys.stderr)
        return None

    if value > 1 or raw.endswith("%"):
        value /= 100.0
    if not 0 <= value < 1:
        print(
            f"Ignoring {ENTERPRISE_DISCOUNT_ENV}={raw!r}: expected a discount "
            f"below 100% off list",
            file=sys.stderr,
        )
        return None

    return value


def format_rate_label(family, version, exact=True):
    label = "{} {}".format(family.title(), ".".join(str(v) for v in version)).strip()
    return label if exact else label + " (nearest)"


def resolve_model_rates(model_name, pricing):
    """Resolve rates for a model id, degrading to the newest version in its family.

    Returns (label, rates); the label names the pricing row that was applied, so
    the report can show exactly which rates produced each cost.
    """
    key = parse_model_key(model_name)
    if key:
        family, version = key
        if (family, version) in pricing:
            return format_rate_label(family, version), pricing[(family, version)]
        same_family = [k for k in pricing if k[0] == family]
        if same_family:
            nearest = max(same_family, key=lambda k: k[1])
            return format_rate_label(nearest[0], nearest[1], exact=False), pricing[nearest]
    return "Unmatched (default rates)", DEFAULT_RATES


def split_usage_tokens(usage):
    """Normalize a usage record, splitting 5m and 1h cache writes when reported."""
    cache_write_total = usage.get("cache_creation_input_tokens") or 0
    breakdown = usage.get("cache_creation")

    if isinstance(breakdown, dict):
        write_5m = breakdown.get("ephemeral_5m_input_tokens") or 0
        write_1h = breakdown.get("ephemeral_1h_input_tokens") or 0
    else:
        write_5m, write_1h = 0, 0

    # Older transcripts only carry the flat total; so do newer ones when the
    # breakdown is present but empty.
    if not (write_5m or write_1h):
        write_5m, write_1h = cache_write_total, 0

    return {
        "input": usage.get("input_tokens") or 0,
        "output": usage.get("output_tokens") or 0,
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
        "cache_read": usage.get("cache_read_input_tokens") or 0,
    }


def calculate_turn_cost(tokens, rates):
    return sum(
        tokens[component] / 1_000_000 * rates[component]
        for component, _ in RATE_COMPONENTS
    )


def clean_summary_text(text, max_len=40):
    """Removes linebreaks and fits the summary perfectly inside its column width."""
    if not text or text == "No summary available":
        return "N/A"
    cleaned = " ".join(text.split())
    # Control characters, byte-order marks and other non-printables break the
    # fixed-width alignment and can be unencodable on the terminal code page.
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    if not cleaned:
        return "N/A"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len-3] + "..."


def render_table(headers, rows, right_align=()):
    """Format a fixed-width table, sizing each column to its widest value."""
    widths = [
        max([len(header)] + [len(row[index]) for row in rows])
        for index, header in enumerate(headers)
    ]

    def format_row(cells):
        return " | ".join(
            cell.rjust(width) if index in right_align else cell.ljust(width)
            for index, (cell, width) in enumerate(zip(cells, widths))
        )

    header_line = format_row(headers)
    lines = ["-" * len(header_line), header_line, "-" * len(header_line)]
    lines.extend(format_row(row) for row in rows)
    lines.append("-" * len(header_line))
    return lines


def build_rates_table(rates_used, enterprise_discount):
    """Render the pricing rows that actually produced the report's costs."""
    headers = ["Model (rate row)"]
    headers.extend(title for _, title in RATE_COMPONENTS)
    headers.extend(["Turns", "Cost"])
    if enterprise_discount is not None:
        headers.append("Cost (Enterprise)")
    headers.append("Matched model IDs")

    rows = []
    for label, entry in sorted(rates_used.items(), key=lambda kv: -kv[1]["cost"]):
        row = [label]
        row.extend(f"${entry['rates'][component]:.2f}" for component, _ in RATE_COMPONENTS)
        row.append(f"{entry['turns']:,d}")
        row.append(f"${entry['cost']:,.4f}")
        if enterprise_discount is not None:
            row.append(f"${entry['cost'] * (1 - enterprise_discount):,.4f}")
        row.append(", ".join(sorted(entry["models"])))
        rows.append(row)

    # Everything between the label and the trailing model IDs is numeric.
    right_align = tuple(range(1, len(headers) - 1))
    return render_table(headers, rows, right_align)


def get_claude_session_details():
    home_dir = os.path.expanduser("~")
    projects_dir = os.path.join(home_dir, ".claude", "projects")

    if not os.path.exists(projects_dir):
        print(f"Directory not found: {projects_dir}. Ensure Claude Code has been initialized.")
        return

    pricing, pricing_source = load_pricing()
    enterprise_discount = load_enterprise_discount()

    current_year_month = datetime.now().strftime("%Y-%m")
    total_cost = 0.0
    session_count = 0

    total_input = 0
    total_output = 0
    total_cache_write = 0
    total_cache_read = 0

    report_start_date = None
    report_end_date = None

    session_records = []
    rates_used = {}

    # Walk through project folders to find .jsonl session logs
    for root, dirs, files in os.walk(projects_dir):
        for file in files:
            if file.endswith(".jsonl"):
                file_path = os.path.join(root, file)
                session_hash = os.path.splitext(file)[0]

                file_cost = 0.0
                file_input = 0
                file_output = 0
                file_cache_write = 0
                file_cache_read = 0
                file_rates_used = {}

                first_prompt = "No summary available"
                in_current_month = False
                session_start = None
                session_end = None

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            data = json.loads(line)

                            # Track session timestamps
                            ts = data.get("timestamp", "")
                            if ts:
                                # Convert ISO timestamp segment to a cleaner layout format
                                # e.g., 2025-03-04T12:34:56.789Z -> 2025-03-04 12:34:56
                                clean_ts = ts.replace("T", " ").split(".")[0]
                                if not session_start or ts < session_start:
                                    session_start = clean_ts
                                if not session_end or ts > session_end:
                                    session_end = clean_ts

                                if current_year_month in ts:
                                    in_current_month = True

                            # Extract token usage and model from assistant records
                            if data.get("type") == "assistant":
                                message = data.get("message", {})
                                usage = message.get("usage", {})
                                model_name = data.get("model") or message.get("model") or "sonnet"

                                if usage:
                                    label, rates = resolve_model_rates(model_name, pricing)
                                    tokens = split_usage_tokens(usage)
                                    turn_cost = calculate_turn_cost(tokens, rates)

                                    file_cost += turn_cost
                                    file_input += tokens["input"]
                                    file_output += tokens["output"]
                                    file_cache_write += tokens["cache_write_5m"] + tokens["cache_write_1h"]
                                    file_cache_read += tokens["cache_read"]

                                    entry = file_rates_used.setdefault(
                                        label,
                                        {"rates": rates, "models": set(), "turns": 0, "cost": 0.0},
                                    )
                                    entry["models"].add(model_name)
                                    entry["turns"] += 1
                                    entry["cost"] += turn_cost

                            # Grab initial user prompt or summary
                            if first_prompt == "No summary available":
                                if data.get("type") == "user":
                                    msg = data.get("message", {})
                                    content = msg.get("content", "")
                                    if isinstance(content, str) and content.strip():
                                        first_prompt = content.strip()
                                    elif isinstance(content, list):
                                        for block in content:
                                            if isinstance(block, dict) and block.get("type") == "text":
                                                first_prompt = block.get("text", "").strip()
                                                break
                                elif "summary" in data:
                                    first_prompt = str(data.get("summary"))

                    if in_current_month:
                        total_cost += file_cost
                        total_input += file_input
                        total_output += file_output
                        total_cache_write += file_cache_write
                        total_cache_read += file_cache_read
                        session_count += 1

                        # Only in-month sessions feed the rate summary, so it
                        # always reconciles with the reported total.
                        for label, entry in file_rates_used.items():
                            overall = rates_used.setdefault(
                                label,
                                {"rates": entry["rates"], "models": set(), "turns": 0, "cost": 0.0},
                            )
                            overall["models"].update(entry["models"])
                            overall["turns"] += entry["turns"]
                            overall["cost"] += entry["cost"]

                        # Track overall report start and end dates
                        if session_start:
                            if not report_start_date or session_start < report_start_date:
                                report_start_date = session_start
                        if session_end:
                            if not report_end_date or session_end > report_end_date:
                                report_end_date = session_end

                        session_records.append({
                            "hash": session_hash,
                            "cost": file_cost,
                            "input": file_input,
                            "output": file_output,
                            "cache_write": file_cache_write,
                            "cache_read": file_cache_read,
                            "start": session_start or "N/A",
                            "end": session_end or "N/A",
                            "overview": first_prompt
                        })

                except (json.JSONDecodeError, UnicodeDecodeError, Exception):
                    continue

    # Sort sessions chronologically by start date
    session_records.sort(key=lambda x: x["start"])

    print(f"\nClaude Code Session Usage Report ({current_year_month})")
    print(f"Report Start Date:         {report_start_date or 'N/A'}")
    print(f"Report End Date:           {report_end_date or 'N/A'}")
    print(f"Pricing Source:            {pricing_source}")
    if enterprise_discount is not None:
        print(f"Enterprise Discount:       {enterprise_discount * 100:.4g}% off list "
              f"(from {ENTERPRISE_DISCOUNT_ENV})")

    # Widths hold the largest realistic values, so rows stay aligned with the
    # header and with each other.
    header = (f"{'Session Hash / ID':<38} | {'Start Date':<19} | {'End Date':<19} | "
              f"{'Cost':<10} | {'Summary':<40} | {'Input Tok':<12} | {'Output Tok':<12} | "
              f"{'Cache R':<15} | {'Cache W':<13}")
    if enterprise_discount is not None:
        header += f" | {'Cost (Ent)':<11}"

    border_line = "-" * len(header)
    print(border_line)
    print(header)
    print(border_line)

    for s in session_records:
        summary_col = clean_summary_text(s['overview'], max_len=40)
        cost_str = f"${s['cost']:.4f}"

        row = (f"{s['hash']:<38} | {s['start']:<19} | {s['end']:<19} | {cost_str:<10} | "
               f"{summary_col:<40} | {s['input']:<12,d} | {s['output']:<12,d} | "
               f"{s['cache_read']:<15,d} | {s['cache_write']:<13,d}")
        if enterprise_discount is not None:
            enterprise_cost = f"${s['cost'] * (1 - enterprise_discount):.4f}"
            row += f" | {enterprise_cost:<11}"
        print(row)

    print(border_line)
    print(f"Total Sessions This Month: {session_count}")
    print(f"Total Token Usage:         Input: {total_input:,d} | Output: {total_output:,d} | Cache Read: {total_cache_read:,d} | Cache Write: {total_cache_write:,d}")
    print(f"Total Estimated Cost:      ${total_cost:.4f}")
    if enterprise_discount is not None:
        print(f"Total Cost (Enterprise):   ${total_cost * (1 - enterprise_discount):.4f}")

    if rates_used:
        print("\nPricing Table Used (USD per million tokens)")
        for line in build_rates_table(rates_used, enterprise_discount):
            print(line)

    if enterprise_discount is None:
        print(f"\nNo Enterprise column: Anthropic does not publish per-token Enterprise rates "
              f"(they are negotiated case by case).\nSet {ENTERPRISE_DISCOUNT_ENV} to your "
              f"contracted discount (e.g. 30 or 0.30) to add one.")
    else:
        print(f"\nEnterprise figures are list price less {enterprise_discount * 100:.4g}%, the "
              f"discount supplied in {ENTERPRISE_DISCOUNT_ENV}.\nThey are not an "
              f"Anthropic-published rate.")
    print()


if __name__ == "__main__":
    # Session summaries can contain characters the terminal's code page cannot
    # encode; replace them rather than crashing mid-report.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    get_claude_session_details()
