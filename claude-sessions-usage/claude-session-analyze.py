import json
import sys
from pathlib import Path

PRICING = {
    "input": 3.00 / 1_000_000,
    "output": 15.00 / 1_000_000,
    "cache_read": 0.30 / 1_000_000,
}

def analyze_and_explain(session_uuid):
    projects_dir = Path.home() / ".claude" / "projects"
    matching_files = list(projects_dir.glob(f"**/{session_uuid}.jsonl"))

    if not matching_files:
        print(f"[ERROR] Session file for UUID '{session_uuid}' not found.", file=sys.stderr)
        return

    target_file = matching_files[0]
    total_cost = 0.0
    step_count = 0
    recent_prompts = []

    print(f"\nAnalyzing Session: {target_file.name}\n" + "="*70)

    with open(target_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line_str = line.strip()
            if not line_str:
                continue

            try:
                data = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            # Capture user text to understand context
            if msg_type == "user":
                content = data.get("message", {}).get("content", "")
                if isinstance(content, list):
                    content = " ".join([c.get("text", "") for c in content if isinstance(c, dict)])
                if content:
                    recent_prompts.append(content[:60].replace("\n", " "))

            # Look for token usage (assistant responses)
            usage = data.get("message", {}).get("usage", {}) or data.get("usage", {})
            if usage:
                step_count += 1
                in_tokens = usage.get("input_tokens", 0)
                out_tokens = usage.get("output_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)

                step_cost = (
                    (in_tokens * PRICING["input"]) +
                    (out_tokens * PRICING["output"]) +
                    (cache_read * PRICING["cache_read"])
                )
                total_cost += step_cost

                # Get a hint of what was being worked on
                context_hint = recent_prompts[-1] if recent_prompts else "Tool execution / background step"
                if len(context_hint) > 50:
                    context_hint = context_hint[:47] + "..."

                # Flag high-cost cache reads
                warning = " ⚠️ [Heavy Context]" if cache_read > 100_000 else ""

                print(f"Step {step_count} | Cost: ${step_cost:.4f}{warning}")
                print(f"  └─ Context: {context_hint}")
                print(f"  └─ Tokens -> Read from memory (Cache): {cache_read:,} | New Output: {out_tokens:,}")

    print("="*70)
    print(f"Total Steps: {step_count}")
    print(f"Estimated Total Cost: ${total_cost:.4f}\n")

    print("💡 Developer Takeaways & How to Improve:")
    print("1. Massive Cache Reads: If your 'Cache Read' is over 100k tokens every step,")
    print("   Claude is re-scanning a massive amount of your codebase or large log files.")
    print("2. How to fix: Keep sessions short. When a task is done, run '/clear'")
    print("   or start a fresh session so Claude doesn't carry forward bloated history.")
    print("3. Avoid feeding giant files or build outputs directly into Claude's chat.")

if __name__ == "__main__":
    target_uuid = "8e3367d8-93f6-4169-8010-a1c339f56528"
    analyze_and_explain(target_uuid)