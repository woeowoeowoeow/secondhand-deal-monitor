#!/usr/bin/env bash
# One-shot deploy: creates the public GitHub repo, stores secrets, creates the
# state branch, optionally stores eBay API keys, and triggers a first cloud run.
# Safe to re-run. Usage:  scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${REPO:-secondhand-deal-monitor}"
CONF="$HOME/.config/secondhand-deal-monitor"

[ -s "$CONF/ntfy_topic" ] || { echo "missing $CONF/ntfy_topic"; exit 1; }
OWNER="$(gh api user -q .login)"

if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  # Public: GitHub Actions minutes are free and unlimited for public repos
  # (a private repo's 2,000 free min/month can't sustain a 5-minute schedule).
  gh repo create "$REPO" --public --source=. --remote=origin --push \
     --description "Local secondhand PC hardware deal monitor (GitHub Actions + ntfy)"
else
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$OWNER/$REPO.git"
  git push -u origin main
fi

gh secret set NTFY_TOPIC -R "$OWNER/$REPO" < "$CONF/ntfy_topic"
gh secret set STATE_SALT -R "$OWNER/$REPO" < "$CONF/state_salt"

if ! git ls-remote --exit-code origin refs/heads/state >/dev/null 2>&1; then
  blob=$(printf '# deal-monitor state (hashed, written by the workflow)\n' | git hash-object -w --stdin)
  tree=$(printf '100644 blob %s\tREADME.md\n' "$blob" | git mktree)
  commit=$(git commit-tree "$tree" -m "init state branch")
  git push origin "$commit:refs/heads/state"
fi

if [ -n "${EBAY_CLIENT_ID:-}" ] && [ -n "${EBAY_CLIENT_SECRET:-}" ]; then
  printf '%s' "$EBAY_CLIENT_ID" | gh secret set EBAY_CLIENT_ID -R "$OWNER/$REPO"
  printf '%s' "$EBAY_CLIENT_SECRET" | gh secret set EBAY_CLIENT_SECRET -R "$OWNER/$REPO"
  echo "eBay keys stored."
fi

gh workflow enable deal-monitor -R "$OWNER/$REPO" >/dev/null 2>&1 || true
gh workflow run deal-monitor -R "$OWNER/$REPO"
echo "Deployed: https://github.com/$OWNER/$REPO/actions"
