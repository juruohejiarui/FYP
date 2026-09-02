import json
import os
from collections import Counter

input_file = "./data/clean/scripts-A.jsonl"
output_file = "./data/convert/scripts-A-v1.jsonl"
invalid_file = "./data/convert/scripts-A-v1_invalid.jsonl"

def analyze_file(filepath):
    if not os.path.exists(filepath):
        return None
    total_lines = 0
    parsable_lines = 0
    dialogue_ids = []
    with open(filepath, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            total_lines += 1
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                parsable_lines += 1
                if "dialogue_id" in data:
                    dialogue_ids.append(data["dialogue_id"])
                elif "dialogue_id" in data.get("meta", {}):
                    dialogue_ids.append(data["meta"]["dialogue_id"])
            except Exception as e:
                pass
    return {
        "total_lines": total_lines,
        "parsable_lines": parsable_lines,
        "dialogue_ids": dialogue_ids,
        "unique_ids": set(dialogue_ids)
    }

print("Analyzing input file...")
input_stats = analyze_file(input_file)
print("Analyzing output file...")
output_stats = analyze_file(output_file)
print("Analyzing invalid file...")
invalid_stats = analyze_file(invalid_file)

if input_stats:
    print(f"Input: total={input_stats['total_lines']}, parsable={input_stats['parsable_lines']}, unique_ids={len(input_stats['unique_ids'])}")
else:
    print("Input file does not exist.")

if output_stats:
    print(f"Output: total={output_stats['total_lines']}, parsable={output_stats['parsable_lines']}, unique_ids={len(output_stats['unique_ids'])}")
else:
    print("Output file does not exist.")

if invalid_stats:
    print(f"Invalid: total={invalid_stats['total_lines']}, parsable={invalid_stats['parsable_lines']}, unique_ids={len(invalid_stats['unique_ids'])}")
else:
    print("Invalid file does not exist.")

# 4) Count of how many dialogue_ids in input are present in output, invalid, both, neither
if input_stats:
    input_ids = set(input_stats["dialogue_ids"])
    output_ids = set(output_stats["dialogue_ids"]) if output_stats else set()
    invalid_ids = set(invalid_stats["dialogue_ids"]) if invalid_stats else set()

    in_output = len(input_ids & output_ids)
    in_invalid = len(input_ids & invalid_ids)
    in_both = len(input_ids & output_ids & invalid_ids)
    in_neither = len(input_ids - (output_ids | invalid_ids))

    print(f"Input unique ids: {len(input_ids)}")
    print(f"In output: {in_output}")
    print(f"In invalid: {in_invalid}")
    print(f"In both output & invalid: {in_both}")
    print(f"In neither (lost): {in_neither}")

    # 5) Check duplicate dialogue_id in input
    id_counts = Counter(input_stats["dialogue_ids"])
    duplicates = {k: v for k, v in id_counts.items() if v > 1}
    print(f"Input duplicates count: {len(duplicates)}")
    top_10 = id_counts.most_common(10)
    print("Top 10 duplicate dialogue_ids in input:")
    for k, v in top_10:
        if v > 1:
            print(f"  {k}: {v}")

# 6) Check duplicate dialogue_id in output + invalid (cross-file as well)
all_out_inv_ids = []
if output_stats:
    all_out_inv_ids.extend(output_stats["dialogue_ids"])
if invalid_stats:
    all_out_inv_ids.extend(invalid_stats["dialogue_ids"])

out_inv_counts = Counter(all_out_inv_ids)
out_inv_duplicates = {k: v for k, v in out_inv_counts.items() if v > 1}
print(f"Output + Invalid duplicates total: {len(out_inv_duplicates)}")
if len(out_inv_duplicates) > 0:
    print("Top duplicate dialogue_ids in Output + Invalid:")
    for k, v in out_inv_counts.most_common(10):
        if v > 1:
            print(f"  {k}: {v}")

