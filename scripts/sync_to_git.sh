#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMMIT_MSG="${1:-"chore: sync project updates and documentation"}"

if [[ -z "$(git status --porcelain)" ]]; then
  echo "Working tree is clean. Checking for unpushed commits..."
  git push origin HEAD
  exit 0
fi

git add -A
git commit -m "$COMMIT_MSG"
git push origin HEAD
echo "Successfully committed and pushed changes to origin."
