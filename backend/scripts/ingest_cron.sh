#!/usr/bin/env bash
# Nightly ingest for Linux and macOS.
#
# Install with `crontab -e` and a line like this, which runs at 04:15 every day
# and appends both streams to a log:
#
#   15 4 * * * /srv/football-ou-analytics/backend/scripts/ingest_cron.sh >> /var/log/ou-ingest.log 2>&1
#
# Fixtures move and results land late, so a daily run is enough; running it
# every few minutes only burns the provider's rate limit.

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND_DIR"

# Credentials come from .env, which the settings object loads. Never inline a
# key here: a crontab is world readable on many systems.
if [[ ! -f .env ]]; then
  echo "$(date -Is) missing $BACKEND_DIR/.env" >&2
  exit 1
fi

source .venv/bin/activate

echo "$(date -Is) starting ingest"
python -m app.pipeline.run_ingest --refresh-predictions --prediction-days 14
echo "$(date -Is) ingest finished"
