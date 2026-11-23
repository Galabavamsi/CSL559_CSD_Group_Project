#!/bin/bash
# Record the demo on the dev server: a fresh database, the API, the phone app's two web builds, then
# scripts/record_demo.py and scripts/compose_demo.py. Results go to /tmp/f2h-demo and, if ARTIFACTS is set, to
# that S3 location.
#     bash scripts/record_demo.sh            everything
#     bash scripts/record_demo.sh mock       only the demo-data pass (the servers must already be up)
set -u
cd "$(dirname "$0")/.."
export PATH=~/node/bin:$PATH
OUT=/tmp/f2h-demo
DB=postgresql://darkstore:darkstore@127.0.0.1:5432/demo
PY=.venv/bin/python

if [ "${1:-}" != "mock" ]; then
  rm -rf $OUT; mkdir -p $OUT
  pkill -f "uvicorn app.main:app --port 8000" 2>/dev/null; pkill -f "http.server 809" 2>/dev/null; sleep 1
  sudo docker exec pg psql -U darkstore -d postgres -qc "DROP DATABASE IF EXISTS demo WITH (FORCE)" -c "CREATE DATABASE demo" 2>/dev/null
  echo "=== the API, on an empty database, with produce and email written to its log"
  DARKSTORE_DB=$DB DEMO_PRODUCE=on DEMO_HUBS=on AGENT_SELF_SIGNUP=on POOL_MAX_WAIT_MINUTES=0 EMAIL_BACKEND=log RATE_LIMIT_PER_SECOND=0 OTP_RESEND_SECONDS=0 REPLENISHMENT_INTERVAL_MINUTES=0 \
    nohup $PY -m uvicorn app.main:app --port 8000 > /tmp/f2h-api.log 2>&1 &
  for _ in $(seq 1 60); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 1; done
  curl -s http://127.0.0.1:8000/health; echo
  echo "=== sales history and delivery lookups, so the hub's dashboards have something to show"
  DARKSTORE_DB=$DB $PY scripts/generate_sales.py 2>&1 | tail -1
  DARKSTORE_DB=$DB $PY scripts/generate_demand.py 2>&1 | tail -1
  echo "=== the phone app's web builds"
  if [ "${BUILD:-1}" = 1 ]; then      # BUILD=0 keeps the builds from the last run
    (cd mobile && npm ci --no-audit --no-fund --loglevel=error >/dev/null 2>&1
     npx expo export --platform web --output-dir dist-mock 2>&1 | tail -1
     EXPO_PUBLIC_API_URL=http://127.0.0.1:8000 npx expo export --platform web --output-dir dist-real 2>&1 | tail -1)
  fi
  nohup python3 -m http.server 8090 --directory mobile/dist-real >/dev/null 2>&1 &
  nohup python3 -m http.server 8091 --directory mobile/dist-mock >/dev/null 2>&1 &
  sleep 2
fi

echo "=== recording"
$PY scripts/record_demo.py $OUT ${1:+$1} 2>&1 | tail -60
status=${PIPESTATUS[0]}
echo "=== composing"
$PY scripts/compose_demo.py $OUT 2>&1 | tail -5
if [ -n "${ARTIFACTS:-}" ]; then
  aws s3 sync $OUT "$ARTIFACTS" --only-show-errors --exclude "compose/*" --exclude "video/*" && echo "uploaded to $ARTIFACTS"
fi
exit $status
