#!/usr/bin/env bash
# Show a global summary table of all benchmark data: task / model / attempts.
set -euo pipefail

cd "$(dirname "$0")"

# Scan results/<task>/<slug>/meta.json to discover runs and count attempts.
summary_lines=()

for task_dir in results/*/; do
    [ -d "$task_dir" ] || continue
    task=$(basename "$task_dir")

    for model_dir in "$task_dir"*/; do
        [ -d "$model_dir" ] || continue
        meta="$model_dir/meta.json"
        [ -f "$meta" ] || continue

        slug=$(python3 -c "import json; print(json.load(open('$meta'))['slug'])")
        data_dir=$(python3 -c "import json; print(json.load(open('$meta')).get('data_dir',''))")

        # Count attempts
        n=0
        if [ -n "$data_dir" ] && [ -d "$data_dir/attempts" ]; then
            n=$(ls "$data_dir/attempts" 2>/dev/null | wc -l | tr -d ' ')
        elif [ -d "$model_dir/attempts" ]; then
            n=$(ls "$model_dir/attempts" 2>/dev/null | wc -l | tr -d ' ')
        fi

        if [ "$n" -gt 0 ]; then
            summary_lines+=("$task $slug $n")
        fi
    done
done

if [ ${#summary_lines[@]} -gt 0 ]; then
    printf "%-25s %-40s %s\n" "Task" "Model" "Attempts"
    printf "%-25s %-40s %s\n" "----" "-----" "--------"
    for line in "${summary_lines[@]}"; do
        read -r task slug attempts <<< "$line"
        printf "%-25s %-40s %s\n" "$task" "$slug" "$attempts"
    done
fi
