import json
from pathlib import Path

# Standard pricing per million tokens (e.g., Claude 3.5 Sonnet)
PRICING = {
    "input": 3.00 / 1_000_000,
    "output": 15.00 / 1_000_000,
    "cache_read": 0.30 / 1_000_000,
}

def analyze_claude_session(file_path):
    path = Path(file_path)
    if not path.exists():
        print(f"File not found: {file_path}")
        return

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cost = 0.0
    step_count = 0

    print(f"\nAnalyzing session: {path.name}\n" + "-"*50)

    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line)
                # Extract usage metrics from standard Claude message logs
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

                    total_input += in_tokens
                    total_output += out_tokens
                    total_cache_read += cache_read
                    total_cost += step_cost

                    print(f"Step {step_count} (Line {line_num}): "
                          f"In: {in_tokens:,} | Out: {out_tokens:,} | "
                          f"Cache Read: {cache_read:,} | Cost: ${step_cost:.4f}")

            except json.JSONDecodeError:
                continue

    print("-"*50)
    print(f"Total Steps: {step_count}")
    print(f"Total Input Tokens: {total_input:,}")
    print(f"Total Output Tokens: {total_output:,}")
    print(f"Total Cache Read Tokens: {total_cache_read:,}")
    print(f"Estimated Total Cost: ${total_cost:.4f}\n")

if __name__ == "__main__":
    # Example: point to a specific .jsonl session file
    # target_file = Path.home() / ".claude" / "projects" / "your-project-dir" / "session-id.jsonl"
    # analyze_claude_session(target_file)
    pass