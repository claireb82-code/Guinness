#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_PATH="$REPO_ROOT/.git/hooks/post-commit"

cat > "$HOOK_PATH" << 'EOF'
#!/usr/bin/env bash
# Automatically push new commits to origin
echo "[post-commit] Automatically pushing commit to origin..."
git push origin HEAD || echo "[post-commit] Warning: git push failed (may require network access or explicit push)."
EOF

chmod +x "$HOOK_PATH"
echo "Installed automatic git push hook at $HOOK_PATH"
