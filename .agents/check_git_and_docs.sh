#!/usr/bin/env bash
# Antigravity Stop hook: Ensures READMEs/documentation are updated and all changes are committed & pushed.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 0

INPUT_JSON="$(cat)"

# Only enforce on normal turn completion (NO_TOOL_CALL)
if ! echo "$INPUT_JSON" | grep -q '"terminationReason"[[:space:]]*:[[:space:]]*"NO_TOOL_CALL"'; then
  echo '{"decision": "allow"}'
  exit 0
fi

DIRTY_STATUS="$(git status --porcelain 2>/dev/null || true)"
if [[ -n "$DIRTY_STATUS" ]]; then
  cat << 'EOF'
{
  "decision": "continue",
  "reason": "Uncommitted changes were detected in the repository. Please ensure README.md and relevant documentation are updated to reflect any code changes, then commit and push all changes to origin/main before finishing."
}
EOF
  exit 0
fi

echo '{"decision": "allow"}'
