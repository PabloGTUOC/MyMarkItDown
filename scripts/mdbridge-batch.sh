#!/usr/bin/env bash
set -euo pipefail

# mdbridge-batch.sh - Folder-to-folder batch conversion via MyMarkItDown API
# Usage: mdbridge-batch.sh [-u URL] [-r|--no-recurse] [-n|--no-frontmatter] [-f|--force] INPUT_DIR OUTPUT_DIR

URL="${MDBRIDGE_URL:-https://md.opinasdeque.es}"
RECURSE=true
FRONTMATTER=true
FORCE=false
INPUT_DIR=""
OUTPUT_DIR=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [-u URL] [-r|--no-recurse] [-n|--no-frontmatter] [-f|--force] INPUT_DIR OUTPUT_DIR

Options:
  -u URL              API base URL (default: \$MDBRIDGE_URL or https://md.opinasdeque.es)
  -r, --no-recurse    Do not recurse into subdirectories (top-level files only)
  -n, --no-frontmatter
                      Disable YAML front matter in generated Markdown
  -f, --force         Force conversion, ignoring incremental mtime checks
  -h, --help          Show this help message
EOF
}

# Parse command line options
while [[ $# -gt 0 ]]; do
  case "$1" in
    -u)
      URL="$2"
      shift 2
      ;;
    -r|--no-recurse)
      RECURSE=false
      shift
      ;;
    -n|--no-frontmatter)
      FRONTMATTER=false
      shift
      ;;
    -f|--force)
      FORCE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Error: Unknown option $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -z "$INPUT_DIR" ]]; then
        INPUT_DIR="$1"
      elif [[ -z "$OUTPUT_DIR" ]]; then
        OUTPUT_DIR="$1"
      else
        echo "Error: Unexpected argument $1" >&2
        usage >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$INPUT_DIR" || -z "$OUTPUT_DIR" ]]; then
  echo "Error: Both INPUT_DIR and OUTPUT_DIR must be specified." >&2
  usage >&2
  exit 1
fi

if [[ ! -d "$INPUT_DIR" ]]; then
  echo "Error: Input directory '$INPUT_DIR' does not exist or is not a directory." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

URL="${URL%/}"

# Setup Cloudflare Access authentication headers if credentials provided
CF_HEADERS=()
if [[ -n "${CF_ACCESS_CLIENT_ID:-}" && -n "${CF_ACCESS_CLIENT_SECRET:-}" ]]; then
  CF_HEADERS+=(-H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}")
fi

# Fetch supported formats from server
FORMATS_JSON=$(curl -fsS "${CF_HEADERS[@]+"${CF_HEADERS[@]}"}" "${URL}/api/formats" 2>/dev/null || true)
if [[ -z "$FORMATS_JSON" ]]; then
  echo "Error: Failed to fetch supported formats from ${URL}/api/formats" >&2
  exit 1
fi

# Parse JSON array without jq using tr, grep, sed
FORMATS_LIST=$(echo "$FORMATS_JSON" | tr -d '[]" ' | tr ',' '\n' | grep -v '^$' | tr '[:upper:]' '[:lower:]' || true)

get_mtime() {
  local f="$1"
  local val
  val=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0)
  if [[ "$val" =~ ^[0-9]+$ ]]; then
    echo "$val"
  else
    echo 0
  fi
}

# Collect files from input directory
FIND_DEPTH=""
if [[ "$RECURSE" == "false" ]]; then
  FIND_DEPTH="-maxdepth 1"
fi

TEMP_SCAN=$(mktemp)
trap 'rm -f "$TEMP_SCAN"' EXIT

# Find all regular files relative to INPUT_DIR
(
  cd "$INPUT_DIR"
  # shellcheck disable=SC2086
  find . $FIND_DEPTH -type f
) | sed 's|^\./||' > "$TEMP_SCAN"

# Identify supported files
SUPPORTED_ITEMS=$(mktemp)
trap 'rm -f "$TEMP_SCAN" "$SUPPORTED_ITEMS"' EXIT

SKIPPED_COUNT=0

while IFS= read -r rel_path; do
  [[ -z "$rel_path" ]] && continue
  base_name=$(basename "$rel_path")
  ext=""
  if [[ "$base_name" == *.* ]]; then
    ext=".${base_name##*.}"
  fi
  ext_lower=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

  # Check if extension is supported
  is_supported=false
  while IFS= read -r fmt; do
    if [[ "$ext_lower" == "$fmt" ]]; then
      is_supported=true
      break
    fi
  done <<< "$FORMATS_LIST"

  if [[ "$is_supported" == "true" ]]; then
    dir_name=$(dirname "$rel_path")
    stem="${base_name%.*}"
    stem_lower=$(echo "$stem" | tr '[:upper:]' '[:lower:]')
    printf "%s\t%s\t%s\t%s\n" "$dir_name" "$stem_lower" "$rel_path" "$base_name" >> "$SUPPORTED_ITEMS"
  else
    SKIPPED_COUNT=$(( SKIPPED_COUNT + 1 ))
  fi
done < "$TEMP_SCAN"

# Resolve output paths using collision rule:
# If two supported files in the same folder share a stem, use <name>.<ext>.md for both; otherwise <stem>.md
PLAN_MAPPING=$(mktemp)
trap 'rm -f "$TEMP_SCAN" "$SUPPORTED_ITEMS" "$PLAN_MAPPING"' EXIT

awk -F"\t" '
  {
    key = $1 "\t" $2;
    count[key]++;
    files[NR] = $0;
  }
  END {
    for (i = 1; i <= NR; i++) {
      split(files[i], parts, "\t");
      d = parts[1];
      stem_lower = parts[2];
      rel = parts[3];
      b = parts[4];
      stem = b;
      sub(/\.[^.]+$/, "", stem);
      key = d "\t" stem_lower;
      if (count[key] > 1) {
        out_name = b ".md";
      } else {
        out_name = stem ".md";
      }
      if (d == ".") {
        target = out_name;
      } else {
        target = d "/" out_name;
      }
      printf "%s\t%s\n", rel, target;
    }
  }
' "$SUPPORTED_ITEMS" > "$PLAN_MAPPING"

CONVERTED_COUNT=0
FAILED_COUNT=0

# Perform conversion item by item
while IFS=$'\t' read -r rel_path target_rel_path; do
  [[ -z "$rel_path" ]] && continue

  source_file="${INPUT_DIR}/${rel_path}"
  target_file="${OUTPUT_DIR}/${target_rel_path}"
  target_dir=$(dirname "$target_file")
  mkdir -p "$target_dir"

  # Incremental check
  if [[ "$FORCE" == "false" && -f "$target_file" ]]; then
    src_mtime=$(get_mtime "$source_file")
    dst_mtime=$(get_mtime "$target_file")
    if [[ "$dst_mtime" -ge "$src_mtime" ]]; then
      SKIPPED_COUNT=$(( SKIPPED_COUNT + 1 ))
      continue
    fi
  fi

  # Temp file for download
  tmp_target="${target_file}.tmp.$$"
  success=false
  attempts=0

  while [[ "$attempts" -lt 2 ]]; do
    attempts=$(( attempts + 1 ))

    # Post file to /api/convert with frontmatter option
    http_code=$(curl -sS -w "%{http_code}" "${CF_HEADERS[@]+"${CF_HEADERS[@]}"}" \
      -F "file=@${source_file}" \
      "${URL}/api/convert?frontmatter=${FRONTMATTER}&format=md" \
      -o "$tmp_target" 2>&1) || true

    # Check for network error
    if [[ ! "$http_code" =~ ^[0-9]{3}$ || "$http_code" == "000" ]]; then
      if [[ "$attempts" -eq 1 ]]; then
        sleep 1
        continue
      fi
      echo "Failed: ${rel_path} (network error)" >&2
      break
    fi

    # 2xx Success
    if [[ "$http_code" -ge 200 && "$http_code" -lt 300 ]]; then
      mv "$tmp_target" "$target_file"
      success=true
      break
    fi

    # 4xx Client error (never retry)
    if [[ "$http_code" -ge 400 && "$http_code" -lt 500 ]]; then
      echo -n "Failed: ${rel_path} (HTTP ${http_code}): " >&2
      cat "$tmp_target" >&2
      echo "" >&2
      break
    fi

    # 5xx Server error (retry once)
    if [[ "$http_code" -ge 500 ]]; then
      if [[ "$attempts" -eq 1 ]]; then
        sleep 1
        continue
      fi
      echo -n "Failed: ${rel_path} (HTTP ${http_code}): " >&2
      cat "$tmp_target" >&2
      echo "" >&2
      break
    fi
  done

  rm -f "$tmp_target"

  if [[ "$success" == "true" ]]; then
    CONVERTED_COUNT=$(( CONVERTED_COUNT + 1 ))
    echo "Converted: ${rel_path} -> ${target_rel_path}"
  else
    FAILED_COUNT=$(( FAILED_COUNT + 1 ))
  fi
done < "$PLAN_MAPPING"

echo "----------------------------------------"
echo "Summary: ${CONVERTED_COUNT} converted, ${SKIPPED_COUNT} skipped, ${FAILED_COUNT} failed"
echo "----------------------------------------"

if [[ "$FAILED_COUNT" -gt 0 ]]; then
  exit 1
fi
exit 0
