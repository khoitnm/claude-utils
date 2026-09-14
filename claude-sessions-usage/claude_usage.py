"""Shared cost-accounting rules for the Claude Code usage reports.

Every rule the reports in this directory must agree on lives here: where rates
come from, how a model id maps to a rate row, how a transcript is split into
billable turns, and how a turn is priced. The scripts are presentation only --
if two reports ever disagree on a number, the cause is a rule that leaked out
of this module and back into a script.

Python 3.6+, standard library only.
"""

import contextlib
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import datetime

# ---------------------------------------------------------------------------
# Where rates come from
# ---------------------------------------------------------------------------

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

# The five separately-priced token components, in report column order. Adding a
# component here flows through pricing, cost, totals and both rate tables.
RATE_COMPONENTS = [
    ("input", "Input"),
    ("cache_write_5m", "5m Cache Write"),
    ("cache_write_1h", "1h Cache Write"),
    ("cache_read", "Cache Read"),
    ("output", "Output"),
]

# Where in a transcript record the model id can be found, most specific first.
MODEL_FALLBACK = "sonnet"


# ---------------------------------------------------------------------------
# Pricing table lookup
# ---------------------------------------------------------------------------

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
        return cached[0], "cached from docs (fetched {})".format(cached[1])

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
            return rates, "live from {} (fetched {})".format(PRICING_URL, fetched_at)
        reason = "pricing table not found in page"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = "{}: {}".format(type(exc).__name__, exc)

    if cached:
        return cached[0], "stale cache (fetched {}); live lookup failed - {}".format(
            cached[1], reason
        )

    return FALLBACK_PRICING, (
        "built-in fallback rates as of {}; live lookup failed - {}".format(
            FALLBACK_RATES_ASOF, reason
        )
    )


def load_enterprise_discount():
    """Read the operator-supplied Enterprise discount, or None if unset."""
    raw = os.environ.get(ENTERPRISE_DISCOUNT_ENV, "").strip()
    if not raw:
        return None

    try:
        value = float(raw.rstrip("%").strip())
    except ValueError:
        print("Ignoring {}={!r}: not a number".format(ENTERPRISE_DISCOUNT_ENV, raw),
              file=sys.stderr)
        return None

    if value > 1 or raw.endswith("%"):
        value /= 100.0
    if not 0 <= value < 1:
        print(
            "Ignoring {}={!r}: expected a discount below 100% off list".format(
                ENTERPRISE_DISCOUNT_ENV, raw
            ),
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
    a report can show exactly which rates produced each cost.
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


# ---------------------------------------------------------------------------
# Reading transcripts
# ---------------------------------------------------------------------------

# What came back from one tool call. `chars` is the serialized size of the
# result as it was handed to the model - the quantity that lands in the
# context and gets re-read on every later turn.
ToolResult = namedtuple("ToolResult", "tool_use_id name chars is_error denied interrupted")

# One block the harness injected rather than the conversation producing it:
# memory files, skill listings, deferred tool schemas, hook output, reminders.
Attachment = namedtuple("Attachment", "kind chars")


class Turn(object):
    """One assistant API response, counted exactly once.

    `blocks` holds the response's content blocks in order, but only when the
    session was read with with_blocks=True; a whole-month report has no use for
    them and they are the bulk of a transcript's bytes.

    `tool_results` and `attachments` hold what arrived *after* this response and
    before the next one - its aftermath. They are attributed this way because
    that is what they cost: whatever a turn drags into the context is paid for
    on the turn after it and every turn beyond. Populated only under
    with_details=True.

    `starts_prompt` marks a turn that answers a fresh human prompt rather than
    continuing the previous one, and `prompt` holds that prompt's text. It is
    the only place a session can be split without cutting a turn off from the
    tool call it was reacting to, so every "should this have been a new
    session" question is asked at these turns. `user_context` is not the same
    thing: it is whatever text came last, harness records included. Both are
    populated only under with_details=True.
    """

    __slots__ = ("model", "usage", "blocks", "user_context", "timestamp",
                 "skill", "tool_results", "attachments", "duration_ms",
                 "starts_prompt", "prompt")

    def __init__(self, model, usage, user_context, timestamp=None, skill=None,
                 starts_prompt=False, prompt=""):
        self.model = model
        self.usage = usage
        self.blocks = []
        self.user_context = user_context
        self.timestamp = timestamp
        self.skill = skill
        self.tool_results = []
        self.attachments = []
        self.duration_ms = None
        self.starts_prompt = starts_prompt
        self.prompt = prompt

    @property
    def tool_uses(self):
        """The tool_use blocks of this response, in order (needs with_blocks)."""
        return [b for b in self.blocks if b.get("type") == "tool_use"]


class Session(object):
    """One transcript file: its billable turns plus the metadata reports show."""

    __slots__ = ("session_id", "path", "turns", "start", "end", "months", "summary",
                 "preamble_attachments", "prompts", "denials")

    def __init__(self, session_id, path):
        self.session_id = session_id
        self.path = path
        self.turns = []
        self.start = None       # "YYYY-MM-DD HH:MM:SS", earliest record
        self.end = None         # "YYYY-MM-DD HH:MM:SS", latest record
        self.months = set()     # every "YYYY-MM" the session has a record in
        self.summary = NO_SUMMARY
        # Everything the harness injected before the first response - the
        # static preamble the whole session then carries.
        self.preamble_attachments = []
        self.prompts = 0        # human turns, i.e. how much steering it took
        self.denials = []       # tool calls the user rejected outright


NO_SUMMARY = "No summary available"


def iter_records(path):
    """Yield the parsed JSON records of a transcript, skipping malformed lines."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def extract_user_text(record):
    """The text of a user record, collapsed to one line, or ""."""
    content = record.get("message", {}).get("content", "")
    if isinstance(content, str):
        return " ".join(content.split())
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return " ".join(block.get("text", "").split())
    return ""


def iter_content_blocks(record):
    """The message content blocks of a record, or an empty list."""
    blocks = record.get("message", {}).get("content")
    return [b for b in blocks if isinstance(b, dict)] if isinstance(blocks, list) else []


def read_session(path, with_blocks=False, with_details=False):
    """Parse one transcript into billable turns plus session metadata.

    THE DEDUP RULE, and the reason this module exists. Claude Code writes one
    JSONL line per content block and repeats the entire `usage` object on every
    one of them, so an assistant turn made of text plus a tool_use shows up as
    two or more lines sharing a single message id. Those lines are one API
    response: they must be billed once, and their content blocks belong to the
    same turn. Counting lines instead of message ids nearly doubles every
    figure on a tool-heavy session.

    with_details additionally records what the harness and the tools fed back
    into the context - tool results, injected attachments, skill attribution,
    turn durations - which is most of a transcript's records and none of what a
    whole-month report needs, hence the flag.
    """
    session = Session(os.path.splitext(os.path.basename(path))[0], path)
    by_message_id = {}
    last_user_context = "Initializing..."
    tool_names = {}         # tool_use id -> tool name, filled as calls are seen
    current = None          # the turn whose aftermath we are collecting
    pending_prompt = True   # a human prompt is waiting for its first response
    pending_text = ""       # and this is what it said

    for record in iter_records(path):
        timestamp = record.get("timestamp", "")
        if timestamp:
            # "2026-03-04T12:34:56.789Z" -> "2026-03-04 12:34:56"
            clean = timestamp.replace("T", " ").split(".")[0]
            if session.start is None or clean < session.start:
                session.start = clean
            if session.end is None or clean > session.end:
                session.end = clean
            session.months.add(timestamp[:7])

        record_type = record.get("type")

        if record_type == "user":
            text = extract_user_text(record)
            if text:
                last_user_context = text
                if session.summary == NO_SUMMARY:
                    session.summary = text
            if with_details and _absorb_user_record(
                    session, record, current, tool_names, text):
                pending_prompt, pending_text = True, text
        elif session.summary == NO_SUMMARY and "summary" in record:
            session.summary = str(record.get("summary"))

        if with_details:
            if record_type == "attachment":
                attachment = record.get("attachment") or {}
                target = current.attachments if current else session.preamble_attachments
                target.append(Attachment(
                    str(attachment.get("type") or "unknown"),
                    len(json.dumps(attachment, default=str)),
                ))
            elif record_type == "system" and record.get("subtype") == "turn_duration":
                if current is not None and record.get("durationMs") is not None:
                    current.duration_ms = record.get("durationMs")

        if record_type != "assistant":
            continue

        message = record.get("message", {})
        usage = message.get("usage")
        if not usage:
            continue

        message_id = message.get("id")
        turn = by_message_id.get(message_id) if message_id else None
        if turn is None:
            model = record.get("model") or message.get("model") or MODEL_FALLBACK
            turn = Turn(model, usage, last_user_context,
                        timestamp=record.get("timestamp"),
                        skill=record.get("attributionSkill"),
                        starts_prompt=pending_prompt,
                        prompt=pending_text)
            pending_prompt, pending_text = False, ""
            session.turns.append(turn)
            if message_id:
                by_message_id[message_id] = turn
        current = turn

        blocks = iter_content_blocks(record)
        if with_blocks:
            turn.blocks.extend(blocks)
        if with_details:
            for block in blocks:
                if block.get("type") == "tool_use":
                    tool_names[block.get("id")] = block.get("name", "unknown")

    return session


# User records the harness writes in the user's voice: a notification that a
# background task finished, an injected reminder, the output of a local
# command. They resume a session without anyone steering it, so they are
# neither prompts nor places the session could have been split. A slash
# command (<command-message>) is the opposite case and does count - the user
# typed it.
HARNESS_PROMPT = re.compile(r"^<(task-notification|system-reminder|local-command-)")


def _is_human_prompt(record, text):
    """Whether a user record is a person steering, rather than the harness."""
    if not text or record.get("isMeta") or record.get("interruptedMessageId"):
        return False
    return not HARNESS_PROMPT.match(text)


def _absorb_user_record(session, record, current, tool_names, text):
    """Fold a user record's tool results into the turn that triggered them.

    A user record is either a real human prompt or the harness returning tool
    output; only the former counts as steering, and only the latter is a
    context cost the preceding turn caused. Returns True when the record was a
    human prompt, so the caller can mark the turn that answers it.
    """
    blocks = iter_content_blocks(record)
    results = [b for b in blocks if b.get("type") == "tool_result"]

    if not results:
        if _is_human_prompt(record, text):
            session.prompts += 1
            return True
        return False

    denial = record.get("toolDenialKind")
    detail = record.get("toolUseResult")
    interrupted = bool(isinstance(detail, dict) and detail.get("interrupted"))

    for block in results:
        tool_use_id = block.get("tool_use_id")
        result = ToolResult(
            tool_use_id=tool_use_id,
            name=tool_names.get(tool_use_id, "unknown"),
            chars=len(json.dumps(block.get("content"), default=str)),
            is_error=bool(block.get("is_error")),
            denied=bool(denial),
            interrupted=interrupted,
        )
        if denial:
            session.denials.append(result)
        if current is not None:
            current.tool_results.append(result)

    return False


# ---------------------------------------------------------------------------
# Pricing a turn
# ---------------------------------------------------------------------------

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


def calculate_component_costs(tokens, rates):
    """The cost each token component contributes, priced separately.

    Reports that ask "where did the money go" need the split, not just the
    sum; deriving it anywhere else would be a second copy of the arithmetic.
    """
    return {
        component: tokens[component] / 1_000_000 * rates[component]
        for component, _ in RATE_COMPONENTS
    }


def calculate_turn_cost(tokens, rates):
    return sum(calculate_component_costs(tokens, rates).values())


PricedTurn = namedtuple("PricedTurn", "label rates tokens cost component_costs")


class CostTally(object):
    """Running totals for a set of turns, and the rate rows that priced them.

    Reports accumulate through this rather than summing by hand, so a per-turn
    figure and the total under it are always produced by the same arithmetic.
    """

    def __init__(self):
        self.tokens = {component: 0 for component, _ in RATE_COMPONENTS}
        self.cost_by_component = {component: 0.0 for component, _ in RATE_COMPONENTS}
        self.cost = 0.0
        self.turns = 0
        self.rates_used = {}

    def add_turn(self, turn, pricing):
        """Price one turn, fold it into the totals, and return the detail."""
        label, rates = resolve_model_rates(turn.model, pricing)
        tokens = split_usage_tokens(turn.usage)
        component_costs = calculate_component_costs(tokens, rates)
        cost = sum(component_costs.values())

        for component in self.tokens:
            self.tokens[component] += tokens[component]
            self.cost_by_component[component] += component_costs[component]
        self.cost += cost
        self.turns += 1

        entry = self.rates_used.setdefault(
            label, {"rates": rates, "models": set(), "turns": 0, "cost": 0.0}
        )
        entry["models"].add(turn.model)
        entry["turns"] += 1
        entry["cost"] += cost

        return PricedTurn(label, rates, tokens, cost, component_costs)

    def merge(self, other):
        """Fold another tally in, keeping the rate breakdown intact."""
        for component in self.tokens:
            self.tokens[component] += other.tokens[component]
            self.cost_by_component[component] += other.cost_by_component[component]
        self.cost += other.cost
        self.turns += other.turns

        for label, entry in other.rates_used.items():
            overall = self.rates_used.setdefault(
                label, {"rates": entry["rates"], "models": set(), "turns": 0, "cost": 0.0}
            )
            overall["models"].update(entry["models"])
            overall["turns"] += entry["turns"]
            overall["cost"] += entry["cost"]

    @property
    def cache_write(self):
        """5m and 1h writes summed, the way both reports display them."""
        return self.tokens["cache_write_5m"] + self.tokens["cache_write_1h"]


def cache_write_of(tokens):
    """The displayed cache-write figure for a single turn's token split."""
    return tokens["cache_write_5m"] + tokens["cache_write_1h"]


def effective_cache_write_rate(tokens, rates):
    """The blended per-token write rate a turn actually paid.

    5m and 1h writes are priced differently, so anything reasoning about the
    cost of *adding* tokens has to use the mix the turn really used rather
    than assuming the cheaper row.
    """
    total = cache_write_of(tokens)
    if not total:
        return rates["cache_write_5m"]
    return (tokens["cache_write_5m"] * rates["cache_write_5m"]
            + tokens["cache_write_1h"] * rates["cache_write_1h"]) / total


def context_size_of(tokens):
    """How many prompt tokens this turn actually carried.

    Every prompt token is billed exactly once per turn, as a cache read, a
    cache write or an uncached input, so their sum is the size of the prefix
    that was sent. This is the number a growing session grows.
    """
    return tokens["cache_read"] + cache_write_of(tokens) + tokens["input"]


def discounted(cost, enterprise_discount):
    return cost * (1 - enterprise_discount)


# ---------------------------------------------------------------------------
# Shared rendering
# ---------------------------------------------------------------------------

def clean_summary_text(text, max_len=40):
    """Removes linebreaks and fits the summary perfectly inside its column width."""
    if not text or text == NO_SUMMARY:
        return "N/A"
    cleaned = " ".join(text.split())
    # Control characters, byte-order marks and other non-printables break the
    # fixed-width alignment and can be unencodable on the terminal code page.
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    if not cleaned:
        return "N/A"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len - 3] + "..."


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


def write_csv(path, headers, rows):
    """Write one table to a CSV beside a report, or None if it cannot be saved.

    Data, not layout: values go out unformatted - no thousands separators, no
    dollar signs, no truncation - because the point of the CSV is that a
    spreadsheet or pandas can sort and filter it. The fixed-width tables in the
    reports are the formatted view of the same numbers.
    """
    if not path:
        return None
    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
    except OSError as exc:
        print("Not saving {}: {}".format(os.path.basename(path), exc), file=sys.stderr)
        return None
    return path


def build_rates_table(rates_used, enterprise_discount):
    """Render the pricing rows that actually produced a report's costs."""
    headers = ["Model (rate row)"]
    headers.extend(title for _, title in RATE_COMPONENTS)
    headers.extend(["Turns", "Cost"])
    if enterprise_discount is not None:
        headers.append("Cost (Enterprise)")
    headers.append("Matched model IDs")

    rows = []
    for label, entry in sorted(rates_used.items(), key=lambda kv: -kv[1]["cost"]):
        row = [label]
        row.extend("${:.2f}".format(entry["rates"][component]) for component, _ in RATE_COMPONENTS)
        row.append("{:,d}".format(entry["turns"]))
        row.append("${:,.4f}".format(entry["cost"]))
        if enterprise_discount is not None:
            row.append("${:,.4f}".format(discounted(entry["cost"], enterprise_discount)))
        row.append(", ".join(sorted(entry["models"])))
        rows.append(row)

    # Everything between the label and the trailing model IDs is numeric.
    right_align = tuple(range(1, len(headers) - 1))
    return render_table(headers, rows, right_align)


def print_pricing_provenance(pricing_source, enterprise_discount, label_width=27):
    """The header lines that state which rates a report used."""
    print("{}{}".format("Pricing Source:".ljust(label_width), pricing_source))
    if enterprise_discount is not None:
        print("{}{:.4g}% off list (from {})".format(
            "Enterprise Discount:".ljust(label_width),
            enterprise_discount * 100,
            ENTERPRISE_DISCOUNT_ENV,
        ))


def print_enterprise_footnote(enterprise_discount):
    """The standing explanation of why there is (or is not) an Enterprise column."""
    if enterprise_discount is None:
        print("\nNo Enterprise column: Anthropic does not publish per-token Enterprise rates "
              "(they are negotiated case by case).\nSet {} to your contracted discount "
              "(e.g. 30 or 0.30) to add one.".format(ENTERPRISE_DISCOUNT_ENV))
    else:
        print("\nEnterprise figures are list price less {:.4g}%, the discount supplied in "
              "{}.\nThey are not an Anthropic-published rate.".format(
                  enterprise_discount * 100, ENTERPRISE_DISCOUNT_ENV))


def projects_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def configure_stdout():
    """Transcript text can contain characters the terminal's code page cannot
    encode; replace them rather than crashing mid-report."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Saving a run's output
# ---------------------------------------------------------------------------

# Every run gets its own folder, so a report is never overwritten and two runs
# can be diffed against each other.
REPORT_ROOT_ENV = "CLAUDE_USAGE_REPORT_DIR"
DEFAULT_REPORT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")

# Local time. Colons are illegal in Windows paths, hence the dashes.
RUN_STAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"


def report_root():
    return os.environ.get(REPORT_ROOT_ENV, "").strip() or DEFAULT_REPORT_ROOT


def safe_name_part(text, fallback="report"):
    """Reduce arbitrary text (a session UUID, say) to a safe filename part."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.")
    return cleaned[:80] or fallback


def make_run_dir(slug, now=None):
    """Create and return this run's folder, named '<local-datetime>_<slug>'."""
    stamp = (now or datetime.now()).strftime(RUN_STAMP_FORMAT)
    base = os.path.join(report_root(), "{}_{}".format(stamp, safe_name_part(slug)))

    candidate, suffix = base, 2
    while os.path.exists(candidate):  # two runs inside the same second
        candidate = "{}-{}".format(base, suffix)
        suffix += 1

    os.makedirs(candidate)
    return candidate


class _Tee(object):
    """Fans stdout writes out to the console and the run's report file."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self._streams:
            stream.flush()

    def isatty(self):
        return False


@contextlib.contextmanager
def report_to_file(slug, filename):
    """Mirror everything printed to stdout into a fresh per-run report folder.

    Yields the report's path, or None if it could not be opened - a report that
    cannot be saved should still reach the console. A run that prints nothing
    (an error handled on stderr) leaves no empty folder behind.
    """
    try:
        run_dir = make_run_dir(slug)
        path = os.path.join(run_dir, filename)
        handle = open(path, "w", encoding="utf-8", errors="replace")
    except OSError as exc:
        print("Not saving a report file: {}".format(exc), file=sys.stderr)
        yield None
        return

    original_stdout = sys.stdout
    sys.stdout = _Tee(original_stdout, handle)
    try:
        yield path
    finally:
        sys.stdout = original_stdout
        handle.close()
        if os.path.getsize(path) == 0:
            shutil.rmtree(run_dir, ignore_errors=True)


def side_file(report_path, filename):
    """Path to a data file in the same run folder as a saved report.

    None when nothing was saved, so a run whose report folder could not be
    created still prints to the console instead of failing on the extra file.
    """
    if not report_path:
        return None
    return os.path.join(os.path.dirname(report_path), filename)


def announce_report(path, *extras):
    """Tell the console where the run was saved. Console only: printed after
    the tee is torn down, so the report does not end with a note about itself."""
    if path and os.path.exists(path):
        print("Report saved to: {}".format(path))
    for extra in extras:
        if extra and os.path.exists(extra):
            print("                 {}".format(extra))
