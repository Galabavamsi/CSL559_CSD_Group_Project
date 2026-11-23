#!/bin/bash
# What a test run does. Runs inside the farm2home-test CodeBuild project (infra/ci.yml), from the root of the
# commit under test. To run the same checks on your own machine you need Docker; then:
#     PG_SOURCE_IMAGE=postgis/postgis:16-3.4 bash infra/ci-test.sh
set -euo pipefail

SOURCE=${PG_SOURCE_IMAGE:-postgis/postgis:16-3.4}
IMAGE=$SOURCE

echo "=== 1. PostgreSQL with PostGIS"
if [ -n "${PG_COPY:-}" ]; then
  # In AWS: use our own copy of the image, and make that copy the first time (see infra/ci.yml for why).
  IMAGE="$PG_COPY:${SOURCE##*:}"
  aws ecr get-login-password | docker login --username AWS --password-stdin "${PG_COPY%%/*}" >/dev/null 2>&1
  if docker pull --quiet "$IMAGE" >/dev/null 2>&1; then
    echo "image from our copy"
  else
    echo "no copy yet: taking the image from Docker Hub and keeping one"
    docker pull --quiet "$SOURCE" >/dev/null
    docker tag "$SOURCE" "$IMAGE"
    docker push --quiet "$IMAGE" >/dev/null || echo "could not keep a copy; carrying on with the image as pulled"
  fi
fi
docker rm -f f2h-test-pg >/dev/null 2>&1 || true
# Durability off: this database lives for one run, and waiting for the disk on every commit doubles the run time.
docker run -d --name f2h-test-pg -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=darkstore -e POSTGRES_PASSWORD=darkstore -e POSTGRES_DB=darkstore "$IMAGE" \
  -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null
# The image creates the database, installs its extensions and then restarts the server once. Wait for the last
# extension it installs, then for the restart, so the tests meet the database exactly as a new deployment would.
for _ in $(seq 1 90); do
  if docker exec f2h-test-pg psql -U darkstore -d darkstore -tAc \
       "SELECT 1 FROM pg_extension WHERE extname = 'postgis_tiger_geocoder'" 2>/dev/null | grep -q 1; then
    break
  fi
  sleep 2
done
sleep 6
docker exec f2h-test-pg psql -U darkstore -d darkstore -tAc "SELECT 'PostGIS ' || postgis_lib_version()"

echo "=== 2. dependencies"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

export DARKSTORE_DB=postgresql://darkstore:darkstore@127.0.0.1:5432/darkstore
export DARKSTORE_TEST_DB=$DARKSTORE_DB

echo "=== 3. the migrations build exactly the tables in models.py"
python -m alembic upgrade head
python -m alembic check

echo "=== 4. the demo pages' scripts parse"
if command -v node >/dev/null 2>&1; then
  for script in web/*.js; do node --check "$script"; done
  echo "$(ls web/*.js | wc -l) scripts"
else
  echo "node is not installed here: skipped"
fi

echo "=== 5. the phone app type-checks"
if [ -f mobile/package.json ]; then
  (cd mobile && npm ci --no-audit --no-fund --loglevel=error && npx tsc --noEmit)
  echo "type-check clean"
else
  echo "no phone app in this commit: skipped"
fi

echo "=== 6. the test suite"
python -m pytest -q
