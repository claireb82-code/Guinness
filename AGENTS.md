# Workspace Guidelines & Automation Rules (`AGENTS.md`)

Whenever making changes in this repository (**Guinness Guide — Switzerland Venue & Menu Finder**), you MUST follow these rules before completing your turn:

1. **Keep Documentation & READMEs Updated**
   - Whenever you add, modify, or remove features, API endpoints, UI components, scripts, or configuration options, update [`README.md`](README.md) and [`scripts/README.md`](scripts/README.md) (as well as module docstrings/comments) so that all documentation accurately reflects the current state of the codebase.
   - Ensure consistent project naming (**Guinness Guide — Switzerland Venue & Menu Finder**) and strict **Guinness-only** terminology across all UI files ([`public/standalone.html`](public/standalone.html), [`src/`](src/)) and backend files ([`app_server.py`](app_server.py), [`server/`](server/)).

2. **Automatically Commit & Push All Changes to Git**
   - After verifying your changes and updating documentation/READMEs, stage all modified and new files (`git add -A`), commit with a clear, descriptive commit message, and push to the remote repository (`git push origin main` or `./scripts/sync_to_git.sh "<commit message>"`).
   - Do not leave uncommitted or unpushed changes in the working tree at the end of a task.
