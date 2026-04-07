#!/bin/bash
# Deploy Claude usage dashboard to GitHub Pages
# Usage: ./deploy.sh [days]
# Requires: ANTHROPIC_ADMIN_KEY env var, git repo with gh-pages or main branch

set -e

DAYS=${1:-30}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

python3 generate_dashboard.py --days "$DAYS" --output index.html

# git push to trigger GitHub Pages update
git add index.html
git commit -m "chore: update dashboard $(date '+%Y-%m-%d %H:%M')" --allow-empty
git push

echo "Done. Dashboard deployed."
