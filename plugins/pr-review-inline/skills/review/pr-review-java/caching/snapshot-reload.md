# Java caching — reloading and replacing a whole snapshot

**Applies to kinds:** A only, plus any cache that replaces its contents wholesale on a timer.

Applies to a full-dataset cache (see [kinds.md](kinds.md)) and to any cache that
replaces its contents wholesale on a timer. For per-key invalidation on write, see
[update-path.md](update-path.md).

## Refresh and replacement


- **Clear-then-refill is a correctness hole**, not just a slow path. Between
  `cache.clear()` and the reload, every reader sees an empty cache: a stampede at
  best, wrong "not found" answers if the cache is authoritative. Build the new
  snapshot into a fresh structure and swap an `AtomicReference` / `volatile` field
  in one step. **Blocker** when the cache is authoritative.
- **Failed refresh.** Serve the previous value (stale but plausible) rather than
  replacing it with nothing or an error placeholder. Whichever is chosen, count it
  and alarm on consecutive failures — a cache that quietly stopped refreshing is
  indistinguishable from a working one until the data is badly wrong.
- **In-flight readers during replacement.** A reader that grabbed the reference
  before the swap keeps using the old snapshot, which is fine *provided* it is a
  consistent whole. A reader that fetches several keys across a swap can observe a
  mix of old and new: if the values are mutually consistent (rates and rules, ids
  and names), cache them as one immutable snapshot object rather than as independent
  keys.
- **A reload overwriting a fresher single-entry refresh.** The silent one, and the
  one reviews miss. Reading the table takes time, so a snapshot is already stale
  when it is written: reload reads at `10:00:00` → a user renames the row and the
  write path refreshes that one entry at `10:00:01` → the reload writes its
  `10:00:00` list at `10:00:03` and the rename disappears from the cache. No error,
  no warning, healthy metrics; you hear about it as "my change didn't save", and
  **shortening the interval to reduce staleness makes it more likely**. The fix is
  either prevention (compare row timestamps/versions before overwriting an entry) or
  repair (record keys refreshed while a reload was in flight, then re-read them
  *after* the snapshot is written). If the PR chose repair, check three things:
  only the **last** reload out may settle the queue (an earlier finisher draining it
  lets a later `putAll` re-clobber those keys); the repair re-reads must not
  re-queue themselves; and a *failed* reload wrote nothing, so its queued keys need
  no repair and must be dropped rather than accumulated while the source is sick.
- **Deleting entries during a reload.** A reload that removes "anything not in the
  list I just read" will delete a row created *after* it started reading. It looks
  like correct clean-up, so nobody notices. Restrict deletion to keys that were
  present **before** the load began.
- **Overlapping reloads.** A scheduled tick can overlap a reload triggered by a
  cold read, or by a previous tick that ran long. Two reloads writing snapshots in
  an unknown order, both mutating shared repair state, is where the subtle bugs
  live. Ask what happens when one reload takes longer than the interval.
- **The reload interval itself.** `@Scheduled` resolves its interval **once, at bean
  initialisation** — a `fixedRateString = "#{...}"` SpEL expression is evaluated
  there too, so a config-driven interval still needs a redeploy. To change it at
  runtime you need a short fixed tick that *checks* whether the configured interval
  has elapsed (re-reading the config each tick), or a `SchedulingConfigurer` with a
  `Trigger`. Two traps in the tick approach: an exact `elapsed >= interval`
  comparison never fires on the intended tick (the tick lands a hair late), and if
  that tick re-stamps the schedule, every interval silently becomes one tick longer
  — allow half a tick of slack. And reading configuration every tick is not free:
  use the narrow accessor, not an aggregate that rebuilds everything and logs a
  warning per absent value.
