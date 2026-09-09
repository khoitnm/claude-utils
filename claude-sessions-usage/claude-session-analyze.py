import json
import sys
from pathlib import Path

PRICING = {
    "input": 3.00 / 1_000_000,
    "output": 15.00 / 1_000_000,
    "cache_read": 0.30 / 1_000_000,
}

def analyze_session_totals(session_uuid):
    projects_dir = Path.home() / ".claude" / "projects"
    matching_files = list(projects_dir.glob(f"**/{session_uuid}.jsonl"))
    
    if not matching_files:
        print(f"[ERROR] Session file for UUID '{session_uuid}' not found under {projects_dir}", file=sys.stderr)
        return

    target_file = matching_files[0]
    seen_message_ids = set()
    
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cost = 0.0
    logical_steps = 0

    print(f"\nAnalyzing Session: {target_file.name}\n" + "="*105)
    print(f"{'Step':<6} | {'Cache Read':<12} | {'Input':<8} | {'Output':<8} | {'Cost':<8} | {'Assistant Action / Response Detail'}")
    print("-" * 105)

    with open(target_file, 'r', encoding='utf-8') as f:
        last_user_context = "Initializing..."
        
        for line in f:
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
                    texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    if texts:
                        last_user_context = texts[0].replace("\n", " ")
                elif isinstance(content, str) and content:
                    last_user_context = content.replace("\n", " ")

            message = data.get("message", {})
            msg_id = message.get("id")

            if msg_id:
                if msg_id in seen_message_ids:
                    continue
                seen_message_ids.add(msg_id)

            usage = message.get("usage", {}) or data.get("usage", {})
            if usage:
                logical_steps += 1
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

                action_parts = []
                content_blocks = message.get("content", [])
                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        b_type = block.get("type")
                        if b_type == "text":
                            txt = block.get("text", "").replace("\n", " ").strip()
                            if txt:
                                action_parts.append(txt[:40])
                        elif b_type == "tool_use":
                            t_name = block.get("name", "unknown")
                            t_input = block.get("input", {})
                            detail = ""
                            if t_name == "Bash":
                                detail = f"({t_input.get('command', '')[:20]})"
                            elif t_name in ("View", "Grep", "Glob", "Edit"):
                                detail = f"({t_input.get('file_path', t_input.get('pattern', ''))[:20]})"
                            action_parts.append(f"[Tool: {t_name}{detail}]")

                action_desc = " | ".join(action_parts) if action_parts else f"User: {last_user_context[:30]}"

                warning_tag = " ⚠️" if cache_read > 100_000 else ""
                snippet = (action_desc[:45] + '..') if len(action_desc) > 47 else action_desc
                print(f"{logical_steps:<6} | {cache_read:<12,} | {in_tokens:<8,} | {out_tokens:<8,} | ${step_cost:<7.4f} | {snippet}{warning_tag}")

    print("="*105)
    print(f"Aggregated Totals Across {logical_steps} Logical Steps:")
    print(f"  • Total Input Tokens:       {total_input:,}")
    print(f"  • Total Output Tokens:      {total_output:,}")
    print(f"  • Total Cache Read Tokens:  {total_cache_read:,}")
    print(f"  • Estimated Total Cost:     ${total_cost:.4f}\n")

if __name__ == "__main__":
    target_uuid = "8e3367d8-93f6-4169-8010-a1c339f56528"
    analyze_session_totals(target_uuid)