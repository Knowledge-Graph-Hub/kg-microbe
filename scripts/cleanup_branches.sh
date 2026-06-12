#!/bin/bash
# Cleanup merged and closed branches from local and remote repository
# Usage: ./scripts/cleanup_branches.sh [--dry-run]

set -e

DRY_RUN=false
if [ "$1" == "--dry-run" ]; then
    DRY_RUN=true
    echo "DRY RUN MODE - No branches will be deleted"
    echo "============================================"
fi

# Branches to never delete
PROTECTED_BRANCHES=(
    "master"
    "main"
    "202512-release-fixes"
    "gh-pages"
)

echo "Fetching latest from remote..."
git fetch --prune

echo ""
echo "=== MERGED BRANCHES (already merged into master) ==="
echo ""

# Get list of merged branches (excluding protected branches)
MERGED_BRANCHES=$(git branch --merged master | grep -v '^\*' | grep -v 'master' | sed 's/^  //')

# Filter out protected branches
BRANCHES_TO_DELETE_LOCAL=()
for branch in $MERGED_BRANCHES; do
    PROTECTED=false
    for protected in "${PROTECTED_BRANCHES[@]}"; do
        if [ "$branch" == "$protected" ]; then
            PROTECTED=true
            break
        fi
    done

    if [ "$PROTECTED" == "false" ]; then
        BRANCHES_TO_DELETE_LOCAL+=("$branch")
    fi
done

echo "Local merged branches to delete (${#BRANCHES_TO_DELETE_LOCAL[@]}):"
printf '%s\n' "${BRANCHES_TO_DELETE_LOCAL[@]}"

echo ""
echo "=== DELETING LOCAL MERGED BRANCHES ==="
echo ""

for branch in "${BRANCHES_TO_DELETE_LOCAL[@]}"; do
    if [ "$DRY_RUN" == "true" ]; then
        echo "[DRY RUN] Would delete local branch: $branch"
    else
        echo "Deleting local branch: $branch"
        git branch -d "$branch" 2>/dev/null || git branch -D "$branch"
    fi
done

echo ""
echo "=== REMOTE BRANCHES ==="
echo ""

# Get merged PRs from GitHub
echo "Fetching merged PR branches from GitHub..."
MERGED_PR_BRANCHES=$(gh pr list --state merged --limit 200 --json headRefName --jq '.[].headRefName' | sort | uniq)

echo "Found $(echo "$MERGED_PR_BRANCHES" | wc -l) merged PR branches"

# Get closed (not merged) PRs from GitHub
echo "Fetching closed PR branches from GitHub..."
CLOSED_PR_BRANCHES=$(gh pr list --state closed --limit 200 --json headRefName --jq '.[].headRefName' | sort | uniq)

echo "Found $(echo "$CLOSED_PR_BRANCHES" | wc -l) closed PR branches"

# Combine merged and closed
ALL_PR_BRANCHES=$(echo -e "$MERGED_PR_BRANCHES\n$CLOSED_PR_BRANCHES" | sort | uniq)

echo ""
echo "=== DELETING REMOTE BRANCHES ==="
echo ""

DELETED_REMOTE_COUNT=0
for branch in $ALL_PR_BRANCHES; do
    # Skip protected branches
    PROTECTED=false
    for protected in "${PROTECTED_BRANCHES[@]}"; do
        if [ "$branch" == "$protected" ]; then
            PROTECTED=true
            break
        fi
    done

    if [ "$PROTECTED" == "true" ]; then
        continue
    fi

    # Check if remote branch exists
    if git ls-remote --heads origin "$branch" | grep -q "refs/heads/$branch$"; then
        if [ "$DRY_RUN" == "true" ]; then
            echo "[DRY RUN] Would delete remote branch: $branch"
            ((DELETED_REMOTE_COUNT++))
        else
            echo "Deleting remote branch: $branch"
            if git push origin --delete "$branch" 2>/dev/null; then
                ((DELETED_REMOTE_COUNT++))
            else
                echo "  ⚠ Failed to delete (may be protected or insufficient permissions)"
            fi
        fi
    else
        # Branch doesn't exist - already deleted
        : # skip silently
    fi
done

echo ""
echo "=== CLEANUP SUMMARY ==="
echo "Local branches deleted: ${#BRANCHES_TO_DELETE_LOCAL[@]}"
echo "Remote branches deleted: $DELETED_REMOTE_COUNT"
echo ""

if [ "$DRY_RUN" == "true" ]; then
    echo "This was a DRY RUN. Run without --dry-run to actually delete branches."
else
    echo "Cleanup complete!"
    echo ""
    echo "Running git remote prune to clean up stale references..."
    git remote prune origin
fi
