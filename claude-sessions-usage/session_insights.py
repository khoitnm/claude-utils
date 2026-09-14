"""Derived findings for a single Claude Code session.

Derivation only, and deliberately a third module: claude_usage.py owns the
cost *rules* the reports must agree on, the report scripts own *presentation*,
and everything here is *inference* on top of both. Nothing in this file
prints; it returns numbers, so the same analysis could feed a different
renderer or a cross-session trend later.

THE IDEA THIS MODULE EXISTS FOR. A per-turn ledger prices a turn by what it
spent at the moment it ran, which is the wrong question for a session you want
to make cheaper. Prompt tokens are re-sent on every subsequent turn, so what a
turn really costs is what it *added* to the context multiplied by how many
turns were still to come. A 20k-token file read on step 20 of a 160-step
session is not a 20k-token expense; it is a 20k x 140 expense. That figure is
what this module calls carry cost, and ranking by it is what turns a ledger
into advice.

Python 3.6+, standard library only.
"""

import re
from collections import namedtuple
from datetime import datetime

import claude_usage as cu

# Transcripts record tool results and injected attachments as text, not as
# token counts, so their share of the context has to be estimated. Four
# characters per token is the usual rule of thumb for English prose and code;
# every figure derived from it is labelled with a ~ in the report.
CHARS_PER_TOKEN = 4.0

# An injected attachment small enough to be noise in a growth label. The
# per-turn token reminders are the reason this exists.
NOISE_TOKENS = 200

# A file read this many times is a re-reading pattern rather than a lookup.
HOTSPOT_TOUCHES = 5

# A fall in context size this large means the history was compacted or cleared,
# not that a turn happened to send less. It matters because everything added
# before such a boundary stops being re-read at it: carry cost has to be
# computed within these spans, never across them, or a compacted session
# produces large negative costs. Smaller falls are treated as jitter.
CONTEXT_DROP_TOKENS = 10_000

# Tool inputs, in the order that best identifies the call.
DETAIL_KEYS = ("file_path", "pattern", "command", "query", "path", "url")

# Tool inputs that name a file outright.
FILE_KEYS = ("file_path", "notebook_path")

# A file-looking token inside a shell command: something with an extension.
# Deliberately greedy - a false positive makes the dependency test *more*
# conservative, which is the safe direction for an estimate of what could have
# been thrown away.
FILE_TOKEN = re.compile(r"[A-Za-z0-9_./\\-]+\.[A-Za-z][A-Za-z0-9]{0,8}")


def approx_tokens(chars):
    return int(chars / CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# The per-step spine
# ---------------------------------------------------------------------------

# One assistant turn, priced, plus what it did to the context.
#   context     prompt tokens this turn carried
#   growth      tokens this turn added over the previous one
#   caused      tokens the *next* turn had to carry because of this one
#   carry_cost  what `caused` cost in total: first write plus every re-read
#   remaining   how many later turns re-read it
Step = namedtuple(
    "Step",
    "index turn priced context growth caused carry_cost remaining cause "
    "rewrite_tokens rewrite_cost gap_seconds",
)

# The context a span opens on, which every turn in that span re-reads: the
# preamble for the first span, a compaction summary plus preamble for any
# later one.
SpanBase = namedtuple("SpanBase", "index tokens cost")

# A session's whole analysis. Presentation picks what it wants from here.
SessionInsights = namedtuple(
    "SessionInsights",
    "session tally steps bases preamble_tokens preamble_cost preamble_payload "
    "segments tool_payload injected_payload category_payload skill_costs "
    "hotspots waste reset compactions rewrites span_seconds "
    "reaches cuts levers",
)


def _parse_timestamp(raw):
    """Parse a transcript ISO timestamp, or None if it is missing or odd."""
    if not raw:
        return None
    clean = str(raw).replace("T", " ").split(".")[0].replace("Z", "").strip()
    try:
        return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _gap_seconds(previous, turn):
    """Wall-clock seconds between two turns, or None if either lacks a stamp."""
    before = _parse_timestamp(previous.timestamp)
    after = _parse_timestamp(turn.timestamp)
    if before is None or after is None:
        return None
    return max(0, int((after - before).total_seconds()))


def _describe_tool(block):
    """A tool call reduced to its name plus its most identifying argument."""
    name = block.get("name", "unknown")
    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        return name
    for key in DETAIL_KEYS:
        value = tool_input.get(key)
        if value:
            detail = " ".join(str(value).split())
            if key == "file_path":
                detail = detail.replace("\\", "/").rsplit("/", 1)[-1]
            return "{}({})".format(name, detail[:46])
    return name


def describe_cause(step):
    """Why the context grew after this step, biggest contributor first.

    Built from attribute_growth rather than from the raw blocks, so the label
    in the per-step table always names the same things the ranked findings
    charge it for.
    """
    by_id = {b.get("id"): b for b in step.turn.tool_uses}
    ordered = sorted(attribute_growth(step), key=lambda c: -c.attributed)

    parts = []
    for contribution in ordered:
        if contribution.attributed < NOISE_TOKENS and parts:
            continue  # per-turn reminders and one-line results are not the story
        if contribution.kind == "tool":
            result = next((r for r in step.turn.tool_results
                           if r.name == contribution.label), None)
            block = by_id.get(result.tool_use_id) if result else None
            label = _describe_tool(block) if block else contribution.label
        elif contribution.kind == "injected":
            label = "injected:" + contribution.label
        else:
            label = contribution.label
        parts.append("{} ~{:,}tok".format(label, contribution.attributed))

    return " + ".join(parts) if parts else "no growth"


def build_steps(session, pricing):
    """Price every turn, then attribute each context addition to its cause.

    Growth observed at turn i was caused by turn i-1, so attribution runs one
    step behind payment. The first turn's context has no preceding turn to
    blame: that is the static preamble, returned separately.
    """
    tally = cu.CostTally()
    priced = [tally.add_turn(turn, pricing) for turn in session.turns]
    count = len(priced)

    # A turn that reports no prompt tokens at all is a `<synthetic>` placeholder
    # the harness writes for a failed request, not a response with a prefix. It
    # is free, so it cannot change any cost - but taken literally it reads as
    # the context collapsing to zero and springing back, which would fake a
    # compaction boundary and then a huge growth spike. Hold the previous size.
    contexts = []
    for p in priced:
        size = cu.context_size_of(p.tokens)
        contexts.append(size if size else (contexts[-1] if contexts else 0))

    # Per-turn rates, so a mixed-model session prices each re-read at the rate
    # of the turn that actually did the reading. `suffix[i]` is the cost of
    # re-reading one token on every turn from i to the end of *its span*.
    read_rate = [p.rates["cache_read"] / 1_000_000 for p in priced]
    write_rate = [cu.effective_cache_write_rate(p.tokens, p.rates) / 1_000_000
                  for p in priced]

    # Where the history was compacted or cleared. Each boundary starts a fresh
    # span whose base context nothing before it is re-read on.
    span_end = [count] * count       # first index after this step's span
    starts = [0] + [i for i in range(1, count)
                    if contexts[i] < contexts[i - 1] - CONTEXT_DROP_TOKENS]
    spans = list(zip(starts, starts[1:] + [count]))
    for start, end in spans:
        for i in range(start, end):
            span_end[i] = end

    suffix = [0.0] * (count + 1)
    for start, end in spans:
        running = 0.0
        for i in range(end - 1, start - 1, -1):
            running += read_rate[i]
            suffix[i] = running

    def lifetime_cost(addition, paid_at):
        """What `addition` tokens cost from `paid_at` to the end of its span.

        Written into the cache once, then re-read by every later turn until the
        history is compacted away.
        """
        if paid_at >= count:
            return 0.0
        end = span_end[paid_at]
        tail = suffix[paid_at + 1] if paid_at + 1 < end else 0.0
        return addition * (write_rate[paid_at] + tail)

    steps = []
    for i in range(count):
        growth = contexts[i] - contexts[i - 1] if i else contexts[i]
        # What this turn handed forward is the growth the *next* turn absorbed -
        # unless the next turn opens a new span, in which case it handed on
        # nothing. Clamped at zero so context jitter cannot pay negative.
        same_span = i + 1 < span_end[i]
        caused = max(0, contexts[i + 1] - contexts[i]) if same_span else 0

        # A turn is normally billed a cache write only for what it added. When
        # it is billed for far more, the cache had expired and the whole prefix
        # was written again - real money, exactly reported, and invisible in a
        # per-turn ledger because it looks like an ordinary write.
        rewrite = max(0, cu.cache_write_of(priced[i].tokens) - max(0, growth))

        steps.append(Step(
            index=i + 1,
            turn=session.turns[i],
            priced=priced[i],
            context=contexts[i],
            growth=growth,
            caused=caused,
            carry_cost=lifetime_cost(caused, i + 1),
            remaining=span_end[i] - 1 - i,
            cause=None,  # needs the finished Step; filled in below
            rewrite_tokens=rewrite,
            rewrite_cost=rewrite * write_rate[i],
            gap_seconds=_gap_seconds(session.turns[i - 1], session.turns[i]) if i else None,
        ))

    steps = [step._replace(cause=describe_cause(step)) for step in steps]

    # Every span opens on a base context that the rest of the span re-reads:
    # the preamble for the first, a compaction summary plus preamble for the
    # rest. What that base cost *at* the opening turn is exactly that turn's
    # prompt bill - no need to model it, and modelling it as a fresh cache
    # write would overstate a span that inherited a warm cache (a subagent
    # transcript reads most of its preamble rather than writing it).
    bases = []
    for start, end in spans:
        opening = priced[start]
        tail = contexts[start] * suffix[start + 1] if start + 1 < end else 0.0
        bases.append(SpanBase(
            index=start + 1,
            tokens=contexts[start],
            cost=(sum(opening.component_costs.values())
                  - opening.component_costs["output"] + tail),
        ))

    return tally, steps, bases


# ---------------------------------------------------------------------------
# Aggregations over the spine
# ---------------------------------------------------------------------------

# One thing that added tokens after a step, and its share of the bill.
#   kind        "tool", "injected", "output" or "unexplained"
#   label       the tool name, attachment kind, or a fixed label
#   target      the file the call touched, when there was one
#   tokens      estimated size of the block itself
#   attributed  how much of the step's *measured* growth this accounts for
#   cost        its share of the step's carry cost
#
# tokens and attributed differ when the estimates overshoot what actually
# landed in the context - a prompt_snapshot attachment, for instance, is the
# transcript recording a prompt rather than a block being added to it. Labels
# and the category split use `attributed`; the payload tables use `tokens`,
# because "how much did this tool emit" is a fair question in its own right.
Contribution = namedtuple("Contribution", "kind label target tokens attributed cost")

# Growth a step caused that its recorded tool results, injected attachments
# and own output do not account for. In practice this is the user's next
# prompt plus any skill or tool schema the harness expanded into the system
# prompt, neither of which the transcript records as a sized block.
UNEXPLAINED = "prompt / system-prompt expansion"


def attribute_growth(step):
    """Split what a step handed forward across everything that added to it.

    Every aggregation in this module runs off this one split, so a tool result
    and an injected attachment on the same step can never each be charged the
    whole of it - which is the trap a per-category split falls into when most
    steps have exactly one of each.

    Shares are proportional to estimated tokens and always total the step's
    measured carry cost, so the categories reconcile against the ledger rather
    than against a second estimate of it.
    """
    contributions = []
    output = step.priced.tokens["output"]
    if output:
        contributions.append(
            Contribution("output", "assistant output", None, output, output, 0.0))

    by_id = {b.get("id"): b for b in step.turn.tool_uses}
    for result in step.turn.tool_results:
        block = by_id.get(result.tool_use_id)
        target = None
        if block and isinstance(block.get("input"), dict):
            target = block["input"].get("file_path")
            if target:
                target = target.replace("\\", "/").rsplit("/", 1)[-1]
        tokens = approx_tokens(result.chars)
        contributions.append(
            Contribution("tool", result.name, target, tokens, tokens, 0.0))

    for attachment in step.turn.attachments:
        tokens = approx_tokens(attachment.chars)
        contributions.append(
            Contribution("injected", attachment.kind, None, tokens, tokens, 0.0))

    accounted = sum(c.tokens for c in contributions)
    residual = max(0, step.caused - accounted)
    if residual:
        contributions.append(
            Contribution("unexplained", UNEXPLAINED, None, residual, residual, 0.0))

    total = accounted + residual
    if not total:
        return []

    # Scale the estimates onto the growth that was actually measured, so a
    # block the transcript over-reports cannot be charged for more than the
    # context grew.
    scale = min(1.0, float(step.caused) / total) if step.caused else 0.0
    return [c._replace(attributed=int(c.tokens * scale),
                       cost=step.carry_cost * c.tokens / total)
            for c in contributions]


Bucket = namedtuple("Bucket", "label calls tokens carry_cost share")


def _rank(rows):
    """Turn (label -> calls, tokens, carry) tallies into ranked buckets."""
    total = sum(carry for _, _, carry in rows.values())
    buckets = [
        Bucket(label, calls, tokens, carry, carry / total if total else 0.0)
        for label, (calls, tokens, carry) in rows.items()
    ]
    return sorted(buckets, key=lambda b: -b.carry_cost)


def _accumulate(rows, label, tokens, cost):
    calls, total_tokens, carry = rows.get(label, (0, 0, 0.0))
    rows[label] = (calls + 1, total_tokens + tokens, carry + cost)


def growth_payload(steps):
    """Where the context came from, by category and by contributor.

    Returns (tools, injections, categories): the first two ranked by what
    carrying them cost and sized by what the blocks contained, the third the
    four-way split that reconciles to the session's measured growth and to its
    total carry cost.
    """
    tools, injections, categories = {}, {}, {}
    for step in steps:
        for contribution in attribute_growth(step):
            _accumulate(categories, contribution.kind,
                        contribution.attributed, contribution.cost)
            if contribution.kind == "tool":
                _accumulate(tools, contribution.label,
                            contribution.tokens, contribution.cost)
            elif contribution.kind == "injected":
                _accumulate(injections, contribution.label,
                            contribution.tokens, contribution.cost)
    return _rank(tools), _rank(injections), _rank(categories)


def preamble_payload(session):
    """What the harness had already injected before the first turn ran.

    Priced as one block by build_steps rather than per attachment, because all
    of it is present from turn one; only its composition is interesting here.
    """
    rows = {}
    for attachment in session.preamble_attachments:
        calls, chars = rows.get(attachment.kind, (0, 0))
        rows[attachment.kind] = (calls + 1, chars + attachment.chars)
    return sorted(
        ((kind, calls, approx_tokens(chars)) for kind, (calls, chars) in rows.items()),
        key=lambda row: -row[2],
    )


def segment_costs(steps, buckets=4):
    """Cost per equal slice of the session, which is how context drift shows up.

    A session that gets steadily more expensive per turn is paying for its own
    history; the ratio between the last slice and the first is how much.
    """
    if not steps:
        return []

    size = max(1, len(steps) // buckets)
    segments = []
    for start in range(0, len(steps), size):
        # The last slice absorbs the remainder rather than leaving a stub.
        chunk = steps[start:] if len(segments) == buckets - 1 else steps[start:start + size]
        if not chunk:
            break
        segments.append((
            chunk[0].index,
            chunk[-1].index,
            sum(s.priced.cost for s in chunk),
            sum(s.context for s in chunk) // len(chunk),
        ))
        if len(segments) == buckets:
            break
    return segments


def skill_costs(steps):
    """Cost split by the skill that was driving, where the transcript says."""
    rows = {}
    for step in steps:
        label = step.turn.skill or "(no skill attribution)"
        turns, cost, output = rows.get(label, (0, 0.0, 0))
        rows[label] = (turns + 1, cost + step.priced.cost,
                       output + step.priced.tokens["output"])
    return sorted(
        ((label, turns, cost, output) for label, (turns, cost, output) in rows.items()),
        key=lambda row: -row[2],
    )


Hotspot = namedtuple("Hotspot", "target touches tokens carry_cost")


def hotspots(steps):
    """Files the session went back to again and again.

    Repeated visits to one file are the cheapest thing to fix in a transcript:
    each one re-pays for content already sitting in the context, and a single
    wider read usually replaces the lot.
    """
    rows = {}
    for step in steps:
        for contribution in attribute_growth(step):
            if contribution.kind == "tool" and contribution.target:
                _accumulate(rows, contribution.target,
                            contribution.tokens, contribution.cost)

    found = [Hotspot(target, touches, tokens, carry)
             for target, (touches, tokens, carry) in rows.items()
             if touches >= HOTSPOT_TOUCHES]
    return sorted(found, key=lambda h: -h.touches)


Waste = namedtuple("Waste", "kind count cost detail")


def waste(steps):
    """Turns that bought nothing: rejections, errors, and repeated calls.

    Priced at the turn's own cost plus its carry cost, because a wasted turn
    still enlarges the context that every later turn re-reads.
    """
    found = []

    def spend(selected):
        return sum(s.priced.cost + s.carry_cost for s in selected)

    for kind, predicate in (
        ("Tool calls that returned an error", lambda r: r.is_error),
        ("Interrupted tool calls", lambda r: r.interrupted),
        ("Tool calls the user rejected", lambda r: r.denied),
    ):
        hits = [s for s in steps if any(predicate(r) for r in s.turn.tool_results)]
        if hits:
            found.append(Waste(kind, len(hits), spend(hits),
                               "steps " + _compact(s.index for s in hits)))

    first_seen = {}
    repeats = []
    for step in steps:
        for block in step.turn.tool_uses:
            tool_input = block.get("input")
            key = (block.get("name"),
                   repr(sorted(tool_input.items())) if isinstance(tool_input, dict)
                   else repr(tool_input))
            if key in first_seen:
                repeats.append((step, first_seen[key]))
            else:
                first_seen[key] = step.index
    if repeats:
        found.append(Waste(
            "Byte-identical repeat tool calls", len(repeats),
            spend([step for step, _ in repeats]),
            ", ".join("step {} repeats step {}".format(s.index, first)
                      for s, first in repeats[:5])))

    return sorted(found, key=lambda w: -w.cost)


def _compact(indexes):
    values = list(indexes)
    shown = ", ".join(str(v) for v in values[:6])
    return shown + (" ..." if len(values) > 6 else "")


# A turn billed a cache write far larger than what it added: the prompt cache
# had expired, so the whole prefix was written again.
REWRITE_TOKENS = 20_000

Rewrite = namedtuple("Rewrite", "index tokens cost gap_seconds")


def cache_rewrites(steps):
    """Turns where an expired cache forced the whole prefix to be re-written.

    This is the one cost in the report that a per-turn ledger cannot show at
    all: the charge appears as an ordinary cache write, indistinguishable from
    a turn that legitimately added a lot. Comparing it against how much the
    context actually grew is what separates the two.
    """
    return sorted(
        (Rewrite(s.index, s.rewrite_tokens, s.rewrite_cost, s.gap_seconds)
         for s in steps if s.rewrite_tokens >= REWRITE_TOKENS),
        key=lambda r: -r.cost,
    )


Compaction = namedtuple("Compaction", "index before after")


def compactions(steps):
    """Points where the history was compacted or cleared away.

    Derived back out of the priced steps rather than passed around, so there is
    one definition of a boundary and build_steps and the findings cannot
    disagree about where they are.
    """
    return [Compaction(step.index, previous.context, step.context)
            for previous, step in zip(steps, steps[1:])
            if step.context < previous.context - CONTEXT_DROP_TOKENS]


Reset = namedtuple("Reset", "index savings dropped_tokens")


def _span_bases(steps, preamble_tokens):
    """The context each step's span opened at; above it is that span's history."""
    boundaries = {c.index for c in compactions(steps)}
    bases, base = [], preamble_tokens
    for step in steps:
        if step.index in boundaries:
            base = step.context
        bases.append(base)
    return bases


def _reset_saving(steps, position, dropped, preamble_tokens):
    """What dropping `dropped` tokens of history after `position` would save.

    Every later turn in the same span carries that much less, against one fresh
    write of the preamble. Only turns inside the span count: past a compaction
    boundary the history would have been dropped anyway, and claiming credit
    for it twice is how this kind of estimate flatters itself.
    """
    step = steps[position]
    later = steps[position + 1:position + 1 + step.remaining]
    if dropped <= 0 or not later:
        return None
    saved = dropped * sum(s.priced.rates["cache_read"] for s in later) / 1_000_000
    return saved - preamble_tokens * cu.effective_cache_write_rate(
        step.priced.tokens, step.priced.rates) / 1_000_000


def best_reset(steps, preamble_tokens):
    """The step at which starting a fresh session would have saved the most.

    This is an upper bound. It assumes the work after the reset needed none of
    the history it dropped - which is exactly the assumption a real /clear has
    to earn, and the reason this is reported as a ceiling rather than a saving.
    `dependency_reach` is what tests that assumption; `cut_points` applies the
    test at the turns where a split was actually available.
    """
    if len(steps) < 4:
        return None

    bases = _span_bases(steps, preamble_tokens)
    best = None
    for position, step in enumerate(steps):
        saved = _reset_saving(steps, position, step.context - bases[position],
                              preamble_tokens)
        if saved is None:
            continue
        if best is None or saved > best.savings:
            best = Reset(step.index, saved, step.context - bases[position])
    return best


# ---------------------------------------------------------------------------
# Did the later work actually need the history?
# ---------------------------------------------------------------------------

# What a step touched, and how far back it went to do it.
#   files     file names this step's tool calls named
#   earliest  the earliest step any of those files was first touched at,
#             or None when the step opened all of them itself
Reach = namedtuple("Reach", "index earliest files")


def _basename(value):
    return str(value).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip("\"'")


def _touched_files(turn):
    """File names this turn's tool calls named, from inputs rather than results.

    Inputs, because they say what the turn *went looking for*; a result only
    says what came back. Shell commands are scanned for file-looking tokens,
    which is imprecise in the conservative direction.
    """
    names = set()
    for block in turn.tool_uses:
        tool_input = block.get("input")
        if not isinstance(tool_input, dict):
            continue
        for key in FILE_KEYS:
            if tool_input.get(key):
                names.add(_basename(tool_input[key]))
        command = tool_input.get("command")
        if isinstance(command, str):
            names.update(_basename(match) for match in FILE_TOKEN.findall(command))
    return {name for name in names if len(name) > 2 and not name.startswith(".")}


SLASH_COMMAND = re.compile(r"<command-name>\s*/?([^<\s]+)")


def prompt_label(turn):
    """The prompt a turn answers, as short as it can be said.

    A slash command arrives as its whole expansion, which says nothing a reader
    needs; its name does.
    """
    text = " ".join((turn.prompt or turn.user_context or "").split())
    match = SLASH_COMMAND.search(text)
    return "/" + match.group(1) if match else text


def dependency_reach(steps):
    """How far back each step reached, which is the question a ledger cannot ask.

    A ledger says what a step *added*; it says nothing about whether anything
    later still needed it, and that is exactly what decides whether the history
    could have been dropped. Files are the one dependency a transcript records
    unambiguously: if a turn opens a file that an earlier turn already opened,
    the work has demonstrably come back to that earlier ground.

    It is evidence, not proof. Reasoning carried in the conversation leaves no
    trace here, so a step with no reach-back may still have depended on
    something said earlier. Read it as the strongest claim the transcript
    supports, not as a guarantee.
    """
    first_seen = {}
    reaches = []
    for step in steps:
        files = _touched_files(step.turn)
        earliest = min((first_seen[name] for name in files if name in first_seen),
                       default=None)
        for name in files:
            first_seen.setdefault(name, step.index)
        reaches.append(Reach(step.index, earliest, files))
    return reaches


def reach_after(steps, reaches, index):
    """The earliest step that the work after `index` went back to."""
    position = index - 1
    if not 0 <= position < len(steps):
        return None
    later = reaches[position + 1:position + 1 + steps[position].remaining]
    return min((r.earliest for r in later if r.earliest is not None), default=None)


# A point the session could have been split at, priced both ways.
#   index           the turn that would have opened the new session
#   dropped         tokens of history the split would have left behind
#   savings         what no longer re-reading them would have saved
#   reaches_back    earliest step the work after the split returned to, or None
#   revisited       how many files the later work went back to across the split
#   reentry_tokens  what re-reading those files would have put back
#   reentry_cost    what carrying that again would have cost
#   net             savings less reentry_cost: the figure to decide on
Cut = namedtuple(
    "Cut",
    "index label dropped savings reaches_back revisited reentry_tokens "
    "reentry_cost net",
)


def file_sizes(steps):
    """Each file's size in context, taken from the largest result that carried it.

    The largest rather than the sum: re-reading a file once puts one copy of it
    back, however many times the session happened to open it.
    """
    sizes = {}
    for step in steps:
        for contribution in attribute_growth(step):
            if contribution.kind == "tool" and contribution.target:
                sizes[contribution.target] = max(
                    sizes.get(contribution.target, 0), contribution.tokens)
    return sizes


def _carry_forward(steps, position, tokens):
    """What putting `tokens` back at `position` would cost for the rest of the span.

    The mirror image of _reset_saving, and the reason a split can be costed
    rather than only bounded: whatever the later work went back to has to be
    re-read into the new session and then carried to the end of it.
    """
    step = steps[position]
    later = steps[position + 1:position + 1 + step.remaining]
    write = cu.effective_cache_write_rate(step.priced.tokens, step.priced.rates)
    reads = sum(s.priced.rates["cache_read"] for s in later)
    return tokens * (write + reads) / 1_000_000


def cut_points(steps, reaches, preamble_tokens):
    """Every turn a fresh session could have started at, priced both ways.

    Only turns answering a new human prompt qualify: cutting anywhere else
    would separate a turn from the tool output it was reacting to.

    Each one is then costed against `dependency_reach`, which is what turns
    "clearing here would have saved up to X" into a decision. A split is not
    ruled out by the later work going back to earlier files - it just has to
    re-read them - and re-reading a file is usually far cheaper than carrying
    the whole history that file arrived with. `net` is that comparison.
    """
    bases = _span_bases(steps, preamble_tokens)
    sizes = file_sizes(steps)

    first_seen = {}
    for reach in reaches:
        for name in reach.files:
            first_seen.setdefault(name, reach.index)

    cuts = []
    for position, step in enumerate(steps):
        if position == 0 or not step.turn.starts_prompt:
            continue
        before = position - 1  # the split falls between these two turns
        dropped = steps[before].context - bases[before]
        savings = _reset_saving(steps, before, dropped, preamble_tokens)
        if savings is None:
            continue

        later = reaches[position:position + 1 + steps[before].remaining]
        revisited = {name for reach in later for name in reach.files
                     if first_seen.get(name, step.index) < step.index}
        reentry_tokens = sum(sizes.get(name, 0) for name in revisited)
        reentry_cost = _carry_forward(steps, before, reentry_tokens)

        cuts.append(Cut(
            index=step.index,
            label=prompt_label(step.turn),
            dropped=dropped,
            savings=savings,
            reaches_back=reach_after(steps, reaches, steps[before].index),
            revisited=len(revisited),
            reentry_tokens=reentry_tokens,
            reentry_cost=reentry_cost,
            net=savings - reentry_cost,
        ))
    return cuts


# ---------------------------------------------------------------------------
# What to do about a given step
# ---------------------------------------------------------------------------

# One tag per step, naming the cheapest thing that would have changed its cost.
# The report prints the ones it used as a legend, so a tag in a table never
# needs looking up somewhere else.
LEVER_HINTS = (
    ("SPLIT", "a new phase starts here, and dropping the history before it "
              "saves more than re-reading what the later work went back to"),
    ("CACHE", "an idle gap expired the prompt cache, so the whole prefix was "
              "re-written at write rates"),
    ("WASTE", "an errored, interrupted or rejected call, which stays in the "
              "context regardless"),
    ("RE-READ", "a file already in the context was opened again - one wider "
                "read replaces the run of narrow ones"),
    ("NARROW", "a large tool result - offset/limit on Read, a tighter Grep, "
               "head on Bash output"),
    ("INJECT", "harness-injected text: memory files, hook output, tool "
               "schemas. Controlled outside the session"),
    ("SCHEMA", "a prompt or a mid-session skill/tool-schema expansion, which "
               "never leaves the context again"),
    ("PROSE", "a long response, re-read by every later turn"),
)

# Growth below this is not worth naming a fix for, whatever caused it.
LEVER_TOKENS = 1_000

# How many split points get the SPLIT tag. Every prompt boundary is a possible
# split; tagging all of them would say only that the session had phases.
TOP_SPLITS = 3


def levers(steps, cuts, hotspot_targets):
    """The one thing most worth changing at each step, or "" where nothing is.

    Ranked by what the fix is worth rather than by what the step contains: a
    split or a wasted call is free to avoid, while a large tool result may well
    have been the work itself.
    """
    worth_splitting = {c.index for c in sorted(cuts, key=lambda c: -c.net)[:TOP_SPLITS]
                       if c.net > 0}
    tagged = {}
    for step in steps:
        top = max(attribute_growth(step), key=lambda c: c.attributed, default=None)
        if step.index in worth_splitting:
            tag = "SPLIT"
        elif step.rewrite_tokens >= REWRITE_TOKENS:
            tag = "CACHE"
        elif any(r.is_error or r.denied or r.interrupted
                 for r in step.turn.tool_results):
            tag = "WASTE"
        elif top is None or top.attributed < LEVER_TOKENS:
            tag = ""
        elif top.kind == "injected":
            tag = "INJECT"
        elif top.kind == "tool":
            tag = "RE-READ" if top.target in hotspot_targets else "NARROW"
        elif top.kind == "unexplained":
            tag = "SCHEMA"
        else:
            tag = "PROSE"
        tagged[step.index] = tag
    return tagged


def _span_seconds(session):
    """Wall-clock length of the session, or None if the timestamps are unusable."""
    if not (session.start and session.end):
        return None
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        start = datetime.strptime(session.start, fmt)
        end = datetime.strptime(session.end, fmt)
    except ValueError:
        return None
    return max(0, int((end - start).total_seconds()))


# ---------------------------------------------------------------------------
# Conclusions
# ---------------------------------------------------------------------------

# A finding worth printing has to be worth acting on. Anything under this
# share of the session is noise dressed up as advice, and anything that rounds
# to zero cents is not a finding at all however large its share.
MATERIAL_SHARE = 0.02
MATERIAL_DOLLARS = 0.005

# How many entries a ranked finding lists before it stops being a summary.
TOP_N = 6

# One conclusion about the session.
#   impact  dollars at stake, and the sort key - findings are ranked by money
#   title   the claim, in one line
#   detail  the evidence, one string per line
#   advice  what to do about it, or None when the finding is only evidence
Finding = namedtuple("Finding", "impact title detail advice")


def _money(value):
    return "${:,.2f}".format(value)


def _share(value, total):
    return "{:.0f}%".format(100.0 * value / total) if total else "n/a"


def _plural(count, noun):
    return "{:,} {}{}".format(count, noun, "" if count == 1 else "s")


def _duration(seconds):
    if seconds is None:
        return "unknown"
    if seconds >= 3600:
        return "{}h {:02d}m".format(seconds // 3600, (seconds % 3600) // 60)
    if seconds >= 60:
        return "{}m".format(seconds // 60)
    return "{}s".format(seconds)


def findings(insights):
    """Every conclusion the numbers support, ranked by what it is worth.

    Ranking by dollars rather than by category is the whole point: it puts the
    one lever that matters for *this* session at the top, instead of printing a
    fixed checklist in a fixed order and leaving the reader to work out which
    line is the expensive one.
    """
    total = insights.tally.cost
    if not (total and insights.steps):
        return []

    found = []

    def add(impact, title, detail, advice=None, always=False):
        if impact < MATERIAL_DOLLARS:
            return
        if always or impact >= total * MATERIAL_SHARE:
            found.append(Finding(impact, title, detail, advice))

    # --- Where the money went at all -------------------------------------
    reread = insights.tally.cost_by_component["cache_read"]
    add(reread,
        "{} of the bill ({}) was re-reading context, not doing work".format(
            _share(reread, total), _money(reread)),
        ["Every prompt token is re-sent on every later turn, so cost scales "
         "with context size x turns, not with what changed.",
         "Generating output cost {}; carrying the conversation cost {}.".format(
             _money(insights.tally.cost_by_component["output"]), _money(reread))],
        "Fewer, larger turns and a smaller live context beat micro-optimising "
        "any single call.",
        always=True)

    # --- Paying twice for context you already sent ------------------------
    rewrite_total = sum(s.rewrite_cost for s in insights.steps)
    if insights.rewrites:
        add(rewrite_total,
            "The prompt cache expired {}, re-writing {:,} tokens for {}".format(
                _plural(len(insights.rewrites), "time"),
                sum(s.rewrite_tokens for s in insights.steps), _money(rewrite_total)),
            ["step {:>4}  re-wrote {:>9,} tok  {:>8}  after a {} gap".format(
                r.index, r.tokens, _money(r.cost), _duration(r.gap_seconds))
             for r in insights.rewrites[:TOP_N]],
            "A cache write costs 12.5-20x a cache read, so an idle gap long "
            "enough to expire the cache re-bills the entire context at write "
            "rates. Long pauses mid-session are far more expensive than they "
            "look; finish a phase or start a new session instead of leaving "
            "one open.")

    # --- The floor you pay before doing anything --------------------------
    add(insights.preamble_cost,
        "The static preamble cost {} ({}) just by existing".format(
            _money(insights.preamble_cost), _share(insights.preamble_cost, total)),
        ["{:,} tokens were already in the context at turn 1, then re-read by "
         "{}.".format(insights.preamble_tokens,
                      _plural(len(insights.steps) - 1, "later turn"))]
        + ["  {:<24} ~{:,} tok".format(kind, tokens)
           for kind, _calls, tokens in insights.preamble_payload[:TOP_N]],
        "This is the price of tool schemas, skill listings, MCP servers and "
        "memory files. Trimming unused MCP servers and skills lowers the floor "
        "under every session, not just this one.")

    # --- What filled the context -----------------------------------------
    for bucket in insights.category_payload:
        if bucket.label != "unexplained":
            continue
        add(bucket.carry_cost,
            "{} of context growth is prompt and system-prompt expansion".format(
                _money(bucket.carry_cost)),
            ["~{:,} tokens of growth match no tool result or injected block.".format(
                bucket.tokens),
             "That is your prompts plus skills and tool schemas the harness "
             "expanded mid-session; transcripts do not record them as sized "
             "blocks, so this is a residual, not a measurement."],
            "Loading a skill mid-session permanently enlarges the context. "
            "Invoking one late in a long session is the expensive case.")

    if insights.tool_payload:
        tool_total = sum(b.carry_cost for b in insights.tool_payload)
        add(tool_total,
            "Tool output cost {} to carry".format(_money(tool_total)),
            ["{:<30} {:>4}x  ~{:>8,} tok  {:>8}  {:>4}".format(
                b.label[:30], b.calls, b.tokens, _money(b.carry_cost),
                _share(b.carry_cost, tool_total))
             for b in insights.tool_payload[:TOP_N]],
            "Narrow the reads that dominate: offset/limit on Read, a tighter "
            "Grep, and piping Bash output through head rather than returning "
            "it whole.")

    if insights.injected_payload:
        injected_total = sum(b.carry_cost for b in insights.injected_payload)
        add(injected_total,
            "Harness-injected blocks cost {} to carry".format(_money(injected_total)),
            ["{:<24} {:>4}x  ~{:>8,} tok  {:>8}".format(
                b.label[:24], b.calls, b.tokens, _money(b.carry_cost))
             for b in insights.injected_payload[:TOP_N]],
            "These are not conversation. Memory files, hook output and "
            "deferred tool schemas are all things you control outside the "
            "session.")

    # --- Cost of length, and the counterfactual ---------------------------
    if len(insights.segments) >= 2:
        first, last = insights.segments[0], insights.segments[-1]
        drift = last[2] - first[2]
        ratio = last[2] / first[2] if first[2] else 0
        add(drift,
            "The same work got {:.1f}x more expensive by the end of the session".format(
                ratio),
            ["steps {:>3}-{:<3}  {:>8}  avg context {:>9,} tok".format(
                start, end, _money(cost), context)
             for start, end, cost, context in insights.segments],
            "Nothing changed about the work; only the context it was carried "
            "on top of. Long sessions pay a compounding tax.")

    if insights.compactions:
        # What compaction costs is not the boundary turn but the summary it
        # leaves behind: a fresh base context that every turn in the new span
        # then re-reads, on top of the history that was paid for and discarded.
        boundaries = {c.index for c in insights.compactions}
        carried = sum(b.cost for b in insights.bases if b.index in boundaries)
        boundary_cost = sum(s.priced.cost for s in insights.steps
                            if s.index in boundaries)
        add(carried + boundary_cost,
            "The context was compacted {} - the session outgrew its window".format(
                _plural(len(insights.compactions), "time")),
            ["step {:>4}  {:>9,} tok -> {:>8,} tok, then re-read for {}".format(
                c.index, c.before, c.after,
                _money(next((b.cost for b in insights.bases if b.index == c.index), 0.0)))
             for c in insights.compactions]
            + ["Producing the summaries cost {}; carrying them afterwards cost "
               "{}. Everything summarised away had been paid for on every turn "
               "right up to the boundary.".format(
                   _money(boundary_cost), _money(carried))],
            "Compaction is the window forcing a reset you did not choose. "
            "Splitting the work into separate sessions puts that boundary "
            "where it costs least, and keeps the summary from dropping "
            "something you still needed.")

    # A split is priced at a prompt boundary, where one was actually available,
    # and net of putting back whatever the later work went back to. That is a
    # decision; the reset ceiling below is only a bound, so it is reported only
    # when there was no boundary to price.
    best = max(insights.cuts, key=lambda c: c.net) if insights.cuts else None
    if best and best.net > 0:
        if best.revisited:
            evidence = ("The work after it went back to {} already in the "
                        "context - {} to re-read and carry again - so the net "
                        "is {}.".format(_plural(best.revisited, "file"),
                                        _money(best.reentry_cost),
                                        _money(best.net)))
        else:
            evidence = ("Nothing after it re-opened a file from before it, so "
                        "there was nothing to put back.")
        add(best.net,
            "Starting a fresh session at step {} was worth {}".format(
                best.index, _money(best.net)),
            ["It answers a new prompt: \"{}\"".format(best.label[:68]),
             "{:,} tokens of history were live by then; dropping them saves "
             "{}.".format(best.dropped, _money(best.savings)),
             evidence,
             "Files are the only dependency a transcript records, so reasoning "
             "carried in the conversation would not show up here."]
            + ["step {:>4}  net {:>8}  drop {:>8,} tok  put back {:>7} ({})".format(
                c.index, _money(c.net), c.dropped, _money(c.reentry_cost),
                _plural(c.revisited, "file"))
               for c in sorted(insights.cuts, key=lambda c: -c.net)[:TOP_N]],
            "Every prompt boundary is a chance to start over, and re-reading a "
            "file is far cheaper than carrying the history it arrived with.")
    elif insights.reset:
        index = insights.reset.index
        floor = reach_after(insights.steps, insights.reaches, index)
        add(insights.reset.savings,
            "Clearing the context at step {} would have saved up to {}".format(
                index, _money(insights.reset.savings)),
            ["{:,} tokens of history were being carried by then.".format(
                insights.reset.dropped_tokens),
             "Ceiling, not a forecast: it assumes the work after step {} "
             "needed none of the history it dropped.".format(index),
             "Later turns went back to files first opened at step {}, which "
             "would have to be re-read.".format(floor) if floor and floor < index
             else "No later turn re-opened a file from before it, so little "
                  "would have had to be re-read.",
             "There was no new prompt after that point to split on, so this "
             "stays a bound rather than a decision."],
            "Split unrelated phases into separate sessions. This transcript "
            "covers several; each one paid for the ones before it.")

    # --- Specific, cheap fixes -------------------------------------------
    ranked = sorted(insights.steps, key=lambda s: -s.carry_cost)[:TOP_N]
    if ranked:
        add(sum(s.carry_cost for s in ranked),
            "The {} costliest single additions account for {}".format(
                len(ranked), _money(sum(s.carry_cost for s in ranked))),
            ["step {:>3}  {:>7}  +{:>7,} tok re-read {:>3}x  {}".format(
                s.index, _money(s.carry_cost), s.caused, s.remaining, s.cause[:72])
             for s in ranked],
            "Carry cost is growth x turns remaining, so an early bulk read is "
            "far dearer than the same read near the end.")

    if insights.hotspots:
        hotspot_total = sum(h.carry_cost for h in insights.hotspots)
        add(hotspot_total,
            "{} files were re-read {}+ times, costing {}".format(
                len(insights.hotspots), HOTSPOT_TOUCHES, _money(hotspot_total)),
            ["{:<34} {:>3} touches  ~{:>7,} tok  {:>8}".format(
                h.target[:34], h.touches, h.tokens, _money(h.carry_cost))
             for h in insights.hotspots[:TOP_N]],
            "Each re-read re-pays for content already in the context. One "
            "wider read usually replaces a run of narrow ones.")

    if insights.waste:
        waste_total = sum(w.cost for w in insights.waste)
        add(waste_total,
            "Turns that bought nothing cost {}".format(_money(waste_total)),
            ["{:<34} {:>3}x  {:>8}  ({})".format(
                w.kind[:34], w.count, _money(w.cost), w.detail[:44])
             for w in insights.waste],
            "Priced at the turn plus its carry cost, because a failed call "
            "stays in the context for the rest of the session.")

    return sorted(found, key=lambda f: -f.impact)


def analyze(session, pricing):
    """Run every derivation over one parsed session."""
    tally, steps, bases = build_steps(session, pricing)
    tools, injections, categories = growth_payload(steps)
    preamble = bases[0] if bases else SpanBase(1, 0, 0.0)
    found_hotspots = hotspots(steps)
    reaches = dependency_reach(steps)
    cuts = cut_points(steps, reaches, preamble.tokens)

    return SessionInsights(
        session=session,
        tally=tally,
        steps=steps,
        bases=bases,
        preamble_tokens=preamble.tokens,
        preamble_cost=preamble.cost,
        preamble_payload=preamble_payload(session),
        segments=segment_costs(steps),
        tool_payload=tools,
        injected_payload=injections,
        category_payload=categories,
        skill_costs=skill_costs(steps),
        hotspots=found_hotspots,
        waste=waste(steps),
        reset=best_reset(steps, preamble.tokens),
        compactions=compactions(steps),
        rewrites=cache_rewrites(steps),
        span_seconds=_span_seconds(session),
        reaches=reaches,
        cuts=cuts,
        levers=levers(steps, cuts, {h.target for h in found_hotspots}),
    )
