#!/bin/bash
set -e

APP="${PM2_APP_NAME:-causewayfm}"

FORCE=0
for arg in "$@"; do
  if [ "$arg" = "--force" ] || [ "$arg" = "-f" ]; then FORCE=1; fi
done

echo "Checking for live listeners..."
LISTENERS=$(curl -s --max-time 15 https://radio.ghostmaster.online/api/now-playing \
  | python3 -c "import json,sys; print((json.load(sys.stdin).get('listeners') or {}).get('current', 0))" 2>/dev/null \
  || echo "unknown")

if [ "$LISTENERS" = "unknown" ]; then
  echo "WARNING: could not read listener count (backend unreachable?)."
  if [ "$FORCE" != 1 ]; then
    echo "Aborting. Re-run with --force to deploy anyway."
    exit 1
  fi
elif [ "$LISTENERS" -gt 0 ]; then
  echo "$LISTENERS listener(s) on air right now."
  if [ "$FORCE" != 1 ]; then
    echo "Aborting so nobody's stream drops. Re-run with --force to deploy anyway."
    exit 1
  fi
  echo "--force given: deploying despite live listeners."
else
  echo "Room empty — deploying."
fi

echo "Deploying Causeway FM Web Player to VPS..."

# Ensure we are in the right directory
cd "$(dirname "$0")/causeway_fm_web"

# Exclude large node_modules and Next.js cache, but sync the source code.
# .env.local is excluded: the live file holds UI-saved secrets (Google OAuth,
# admin email, Sub/Wave creds) that must never be clobbered by the repo copy.
rsync -avz --exclude 'node_modules' --exclude '.next' --exclude 'data' --exclude '.env.local' ./ root@ghostmaster.online:/var/www/causewayfm/

echo "Source code synced. Building and restarting on remote server..."

APP="$APP" ssh -o BatchMode=yes root@ghostmaster.online << 'REMOTE'
cd /var/www/causewayfm
npm install
export $(grep ^DATABASE_URL .env.local | xargs)
npx -y prisma generate
npx -y prisma db push
npm run build
pm2 restart "$APP"
REMOTE

echo "Deployment complete!"
