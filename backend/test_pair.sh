#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${BASE_URL:-http://127.0.0.1:8000}
ADDRESS=${1:-78:BD:BC:96:AC:07}
NAME=${2:-"My TV"}

echo "Posting pairing job for $ADDRESS"
resp=$(curl -s -X POST -H "Content-Type: application/json" -d "{\"address\":\"$ADDRESS\",\"name\":\"$NAME\"}" "$BASE_URL/api/pairings/jobs")
echo "Response: $resp"

JOB_ID=$(printf '%s' "$resp" | python3 - <<'PY'
import sys, json
s = sys.stdin.read()
if not s.strip():
    print("")
else:
    try:
        obj = json.loads(s)
        print(obj.get('job_id') or obj.get('id') or obj.get('job') or '')
    except Exception:
        print("")
PY
)

if [ -z "$JOB_ID" ]; then
  echo "No JOB_ID returned; response body was: $resp"
  exit 1
fi

echo "JOB_ID=$JOB_ID"
end=$(( $(date +%s) + 180 ))
while [ $(date +%s) -lt $end ]; do
  r=$(curl -s "$BASE_URL/api/pairings/jobs/$JOB_ID")
  status=$(printf '%s' "$r" | python3 -c "import sys,json; s=sys.stdin.read().strip(); print(json.loads(s).get('status','') if s else '')" 2>/dev/null || echo "")
  echo "status: ${status:-<no-status>}"
  if [ "$status" = "success" ] || [ "$status" = "failed" ]; then
    echo "Final job JSON: $r"
    exit 0
  fi
  sleep 2
done

echo "Timed out waiting for job. Last job JSON: $r"
exit 1
