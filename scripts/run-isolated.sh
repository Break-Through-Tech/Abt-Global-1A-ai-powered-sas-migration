#!/usr/bin/env sh
set -eu

script=${1:-main.py}
generated_directory=${SASGUARD_GENERATED_DIR:-generated}
input_directory=${SASGUARD_INPUT_DIR:-data/Project_1/Starrating}
output_directory=${SASGUARD_OUTPUT_DIR:-reports/runner-output}
result_directory=${SASGUARD_RESULT_DIR:-reports/runner-results}
timeout_seconds=${SASGUARD_TIMEOUT_SECONDS:-60}

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(dirname -- "$script_directory")

case "$generated_directory" in
    /*) source_path=$generated_directory ;;
    *) source_path=$project_root/$generated_directory ;;
esac
case "$input_directory" in
    /*) input_path=$input_directory ;;
    *) input_path=$project_root/$input_directory ;;
esac
case "$output_directory" in
    /*) output_path=$output_directory ;;
    *) output_path=$project_root/$output_directory ;;
esac
case "$result_directory" in
    /*) result_path=$result_directory ;;
    *) result_path=$project_root/$result_directory ;;
esac

source_path=$(CDPATH= cd -- "$source_path" && pwd -P)
input_path=$(CDPATH= cd -- "$input_path" && pwd -P)
mkdir -p -- "$output_path"
output_path=$(CDPATH= cd -- "$output_path" && pwd -P)
mkdir -p -- "$result_path"
result_path=$(CDPATH= cd -- "$result_path" && pwd -P)

for path in "$source_path" "$input_path" "$output_path" "$result_path"; do
    case "$path/" in
        "$project_root"/*) ;;
        *) echo "Runner directories must stay beneath the repository root: $path" >&2; exit 2 ;;
    esac
done

paths_overlap() {
    case "$1/" in "$2/"*) return 0 ;; esac
    case "$2/" in "$1/"*) return 0 ;; esac
    return 1
}

if paths_overlap "$source_path" "$input_path" || \
    paths_overlap "$source_path" "$output_path" || \
    paths_overlap "$input_path" "$output_path" || \
    paths_overlap "$source_path" "$result_path" || \
    paths_overlap "$input_path" "$result_path" || \
    paths_overlap "$output_path" "$result_path"; then
    echo "Source, input, output, and result directories must not overlap." >&2
    exit 2
fi

for forbidden_directory in \
    "$project_root/data/Project_1/SAS Output CSV" \
    "$project_root/data/Project_1/SAS Output"; do
    for candidate in "$source_path" "$input_path" "$output_path" "$result_path"; do
        if paths_overlap "$candidate" "$forbidden_directory"; then
            echo "Runner directory overlaps a trusted golden-output path: $candidate" >&2
            exit 2
        fi
    done
done

case "$script" in
    /*|../*|*/../*|*/..|..) echo "Script must stay beneath the generated directory: $script" >&2; exit 2 ;;
esac
case "$script" in
    *.py) ;;
    *) echo "Script must be a relative .py path: $script" >&2; exit 2 ;;
esac
if [ ! -f "$source_path/$script" ]; then
    echo "Generated entry point does not exist: $source_path/$script" >&2
    exit 2
fi

case "$timeout_seconds" in
    *[!0-9]*|'') echo "Timeout must be an integer from 1 to 600" >&2; exit 2 ;;
esac
if [ "$timeout_seconds" -lt 1 ] || [ "$timeout_seconds" -gt 600 ]; then
    echo "Timeout must be an integer from 1 to 600" >&2
    exit 2
fi

export SASGUARD_GENERATED_DIR=$source_path
export SASGUARD_INPUT_DIR=$input_path
export SASGUARD_OUTPUT_DIR=$output_path
export SASGUARD_SCRIPT=$script
export SASGUARD_TIMEOUT_SECONDS=$timeout_seconds
export SASGUARD_RUNNER_UID=$(id -u)
export SASGUARD_RUNNER_GID=$(id -g)

cd -- "$project_root"
docker compose --profile runner build runner
result_json=$(
    docker compose --profile runner run --rm \
        --user "$SASGUARD_RUNNER_UID:$SASGUARD_RUNNER_GID" runner
)
printf '%s\n' "$result_json" > "$result_path/execution-result.json"
printf 'Execution result written to %s\n' "$result_path/execution-result.json"
