#!/bin/bash
# Smoke test of a deployed environment from outside it. Run it from any machine with curl and openssl, after a deploy:
#     bash infra/smoke.sh https://staging.<domain>
# It needs no login. It makes one checkout hold and releases it, and sends two requests the firewall should block.
# Expected: every line as its note says; "burst" all 200. The burst stays under the app's own limit of 40 calls at
# once from one address on its open endpoints.
set -u
BASE=${1:?usage: smoke.sh https://<host>}
HOST=${BASE#https://}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@"; }
burst() {   # $1 parallel calls to an endpoint that reads the database; prints how many got each status
  seq 1 "$1" | xargs -P "$1" -I{} curl -s -o /dev/null -w '%{http_code}\n' --max-time 30 "$BASE/v1/cities" | sort | uniq -c | tr '\n' ' '
}

echo " 1. health:                $(curl -s --max-time 20 "$BASE/health")"
echo " 2. http redirects:        $(curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' --max-time 20 "http://$HOST/health")"
echo " 3. certificate and TLS:   $(curl -s -o /dev/null -w 'verify=%{ssl_verify_result} (0 is good), HTTP/%{http_version}' --max-time 20 "$BASE/health"), $(echo | openssl s_client -connect "$HOST:443" -servername "$HOST" 2>/dev/null | grep -E 'New, TLS' | head -1)"
echo "    TLS 1.1 refused:       $(curl -s -o /dev/null --tls-max 1.1 --max-time 10 "$BASE/health"; echo "curl exit $? (35 = handshake refused)")"
echo " 4. cities:                $(curl -s --max-time 20 "$BASE/v1/cities" | cut -c1-110)"
echo " 5. a point a hub serves:  $(curl -s --max-time 20 "$BASE/v1/serviceability?lat=12.9716&lng=77.5946" | cut -c1-110)"
echo "    a point in Bhilai:     $(curl -s --max-time 20 "$BASE/v1/serviceability?lat=21.1938&lng=81.3509" | cut -c1-110)"
echo "    a point none serves:   $(curl -s --max-time 20 "$BASE/v1/serviceability?lat=21.266&lng=81.519" | cut -c1-140)"
echo " 6. pages:                 demo $(code "$BASE/"), staff-login.js $(code "$BASE/staff-login.js"), API docs $(code "$BASE/docs")"
echo " 7. built-in password:     $(code -X POST "$BASE/v1/auth/login" -H 'Content-Type: application/json' -d '{"username":"ops","password":"demo"}') (401 = refused, as a hosted site should)"
echo " 8. staff call, no token:  $(code "$BASE/v1/stores/1/dashboard") (401)"
echo " 9. firewall:              script tag in the query $(code "$BASE/v1/stores?q=%3Cscript%3Ealert(1)%3C/script%3E") (403), no user agent $(code -H 'User-Agent:' "$BASE/health") (403), ordinary call $(code "$BASE/v1/stores") (200)"
HOLD=$(curl -s --max-time 20 -X POST "$BASE/v1/reservations" -H 'Content-Type: application/json' \
  -d "{\"order_id\":\"smoke-$RANDOM$RANDOM\",\"store_id\":1,\"lines\":[{\"sku_id\":2,\"qty\":1}]}")
RID=$(echo "$HOLD" | sed -n 's/.*"reservation_id":"\([^"]*\)".*/\1/p')
echo "10. checkout hold:         made=$([ -n "$RID" ] && echo yes || echo "NO: $(echo "$HOLD" | cut -c1-120)"), released $([ -n "$RID" ] && code -X DELETE "$BASE/v1/reservations/$RID")"
echo "11. WebSocket upgrade:     $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 --http1.1 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "$BASE/v1/ws/events?store_id=1") (101 = the load balancer passes WebSockets)"
echo "12. burst of 20 at once:   $(burst 20)"
