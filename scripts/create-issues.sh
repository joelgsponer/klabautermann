#!/bin/bash
# create-issues.sh - Batch create GitHub issues from JSON data
# Usage: ./scripts/create-issues.sh [--dry-run] [--category CATEGORY] [--limit N]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_FILE="${SCRIPT_DIR}/issues.json"
DRY_RUN=false
CATEGORY=""
LIMIT=0
DELAY=2  # Seconds between API calls to avoid rate limiting

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check dependencies
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required. Install with: sudo apt install jq"
    exit 1
fi

if ! command -v gh &> /dev/null; then
    echo "Error: gh (GitHub CLI) is required. Install from: https://cli.github.com/"
    exit 1
fi

# Check authentication
if ! gh auth status &> /dev/null; then
    echo "Error: Not authenticated with GitHub. Run: gh auth login"
    exit 1
fi

# Check data file exists
if [[ ! -f "$DATA_FILE" ]]; then
    echo "Error: Issue data file not found: $DATA_FILE"
    exit 1
fi

# Count issues
TOTAL=$(jq '.issues | length' "$DATA_FILE")
echo "Found $TOTAL issues in $DATA_FILE"

# Filter by category if specified
FILTER=".issues"
if [[ -n "$CATEGORY" ]]; then
    FILTER=".issues | map(select(.category == \"$CATEGORY\"))"
    FILTERED=$(jq "$FILTER | length" "$DATA_FILE")
    echo "Filtered to $FILTERED issues in category: $CATEGORY"
fi

# Apply limit
if [[ $LIMIT -gt 0 ]]; then
    FILTER="$FILTER | .[0:$LIMIT]"
fi

# Get issues to create
ISSUES=$(jq -c "$FILTER | .[]" "$DATA_FILE")

CREATED=0
SKIPPED=0
FAILED=0

while IFS= read -r issue; do
    [[ -z "$issue" ]] && continue

    # Extract fields
    ID=$(echo "$issue" | jq -r '.id')
    TITLE=$(echo "$issue" | jq -r '.title')
    BODY=$(echo "$issue" | jq -r '.body')
    LABELS=$(echo "$issue" | jq -r '.labels | join(",")')

    if $DRY_RUN; then
        echo "DRY-RUN: Would create issue: $ID - $TITLE"
        echo "  Labels: $LABELS"
        ((CREATED++)) || true
    else
        # Check if issue already exists (by title search - only when not dry-run)
        EXISTING=$(gh issue list --search "$ID in:title" --json number --limit 1 2>/dev/null || echo "[]")
        if [[ $(echo "$EXISTING" | jq 'length') -gt 0 ]]; then
            echo "SKIP: $ID - Issue already exists"
            ((SKIPPED++)) || true
            continue
        fi

        echo "Creating: $ID - $TITLE"

        # Create issue
        RESULT=$(gh issue create \
            --title "$TITLE" \
            --body "$BODY" \
            --label "$LABELS" \
            2>&1) || {
            echo "FAILED: $ID - $RESULT"
            ((FAILED++)) || true
            continue
        }

        echo "  Created: $RESULT"
        ((CREATED++)) || true

        # Rate limit delay
        sleep $DELAY
    fi
done <<< "$ISSUES"

echo ""
echo "========================================="
echo "Summary:"
echo "  Created: $CREATED"
echo "  Skipped: $SKIPPED"
echo "  Failed:  $FAILED"
echo "========================================="
