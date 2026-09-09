import json
import sys
from pathlib import Path

PRICING = {
    "input": 3.00 / 1_000_000,
    "output": 15.00 / 1_000_000,
    "cache_read": 0.30 / 1_000_000,
}

def analyze_and_generate_advice(session_uuid):
    projects_dir = Path.home() / ".claude" / "projects"
    matching_files = list(projects_dir.glob(f"**/{session_uuid}.jsonl"))

    if not matching_files:
        print(f"[ERROR] Session file for UUID '{session_uuid}' not found under {projects_dir}", file=sys.stderr)
        return

    target_file = matching_files[0]
    total_cost = 0.0
    step_count = 0
    steps_data = []
    recent_prompts = []

    print(f"\nAnalyzing Session: {target_file.name}\n" + "="*85)

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

            if msg_type == "user":
                content = data.get("message", {}).get("content", "")
                if isinstance(content, list):
                    content = " ".join([c.get("text", "") for c in content if isinstance(c, dict)])
                if content:
                    recent_prompts.append(content[:80].replace("\n", " "))

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

                current_prompt = recent_prompts[-1] if recent_prompts else "Background / Tool step"

                steps_data.append({
                    "step": step_count,
                    "cache_read": cache_read,
                    "output": out_tokens,
                    "cost": step_cost,
                    "prompt": current_prompt
                })

    # Print Table Header
    print(f"{'Step':<6} | {'Cache Read Tokens':<18} | {'Output':<8} | {'Cost':<8} | {'Context Summary'}")
    print("-" * 85)

    for s in steps_data:
        warning_tag = " ⚠️" if s["cache_read"] > 100_000 else ""
        prompt_snippet = (s["prompt"][:35] + '..') if len(s["prompt"]) > 37 else s["prompt"]
        print(f"{s['step']:<6} | {s['cache_read']:<18,} | {s['output']:<8,} | ${s['cost']:<7.4f} | {prompt_snippet}{warning_tag}")

    print("="*85)
    print(f"Total Steps: {step_count} | Estimated Total Cost: ${total_cost:.4f}\n")

    print("🎯 Automated Session Insights & Recommendations:\n")

    if step_count > 100:
        print(f"• Break Tasks into Micro-Sessions: This session reached {step_count} steps. "
              f"Never let a session drag past 50–100 steps. Once you finish a logical chunk of work "
              f"(like switching branches or debugging a specific ticket), type `/clear` or exit and start "
              f"a brand-new session to drop your base context back down to near zero.\n")

    peak_cache = max([s["cache_read"] for s in steps_data]) if steps_data else 0
    if peak_cache > 150_000:
        print(f"• Constrain Project Indexing: Peak cache read hit {peak_cache:,} tokens. "
              f"If Claude Code is automatically scanning your entire repository structure, massive config files, "
              f"or build outputs into the prompt on startup, add a `.claudeignore` file to your project root "
              f"to exclude unnecessary files.\n")

    loops_found = []
    current_streak = 1
    for i in range(1, len(steps_data)):
        if steps_data[i]["prompt"] == steps_data[i-1]["prompt"] and steps_data[i]["cache_read"] > 100_000:
            current_streak += 1
        else:
            if current_streak >= 3:
                loops_found.append((steps_data[i-1]["step"] - current_streak + 1, steps_data[i-1]["step"], steps_data[i-1]["prompt"]))
            current_streak = 1
    if current_streak >= 3:
        loops_found.append((steps_data[-1]["step"] - current_streak + 1, steps_data[-1]["step"], steps_data[-1]["prompt"]))

    if loops_found:
        for start_s, end_s, prompt_text in loops_found:
            print(f"• Stop Multi-Turn Loops: Notice how Steps {start_s} through {end_s} all processed heavy context "
                  f"with the exact same prompt (\"{prompt_text[:40]}...\"). "
                  f"Claude Code got stuck in an internal tool-calling or retry loop. If you see Claude repeating "
                  f"the same action, interrupt it with `Ctrl+C` or instruct it directly: \"Stop retrying, do it in one shot.\"\n")

    if step_count > 150 and peak_cache > 200_000:
        print(f"• Avoid Monolithic Workflows: Trying to code, debug, reproduce, and interact with external systems "
              f"(like JIRA) all in one single {step_count}-step conversation guarantees massive token accumulation. "
              f"Handle code fixes in one session, close it, and open a fresh session to handle documentation or ticket updates.\n")

if __name__ == "__main__":
    target_uuid = "8e3367d8-93f6-4169-8010-a1c339f56528"
    analyze_and_generate_advice(target_uuid)