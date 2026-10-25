#!/usr/bin/env bash
# Docker integration test for the Tang add-on: builds the real image, unlocks with a real Clevis client, checks
# the request log, the JWE kid and key thumbprints, then runs the add-on's one-step test script against a real
# LUKS2 loop disk. Standalone (not collected by pytest). Usage: bash tests/integration/run.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
IMAGE=tang-addon:test
NET=tangtest
TANG=tang
CLIENT=tangtest-client
# A named volume, not a macOS bind mount: Docker Desktop's file sharing rejects tangd-keygen's chmod, and HA's
# /data is a native Linux filesystem anyway.
DATA=tangtest-data
LOOP=""

cleanup() {
  set +e
  if [ -n "$LOOP" ]; then docker exec "$CLIENT" losetup -d "$LOOP" >/dev/null 2>&1; fi
  docker rm -f "$TANG" "$CLIENT" >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
  docker volume rm "$DATA" >/dev/null 2>&1
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  echo "--- add-on logs ---" >&2
  docker logs "$TANG" >&2 2>&1 || true
  exit 1
}

# Remove leftovers from an earlier interrupted run.
docker rm -f "$TANG" "$CLIENT" >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true
docker volume rm "$DATA" >/dev/null 2>&1 || true

echo "== build $IMAGE"
docker build -q -t "$IMAGE" --build-arg BUILD_FROM=ghcr.io/home-assistant/base-debian:trixie "$ROOT/tang" >/dev/null

docker network create "$NET" >/dev/null
docker volume create "$DATA" >/dev/null
docker run --rm -v "$DATA:/data" debian:trixie \
  sh -c 'echo "{\"known_devices\":[],\"address_reserved\":false}" > /data/options.json'

start_tang() {
  docker run -d --name "$TANG" --network "$NET" -v "$DATA:/data" "$@" "$IMAGE" >/dev/null
}

api_state() {
  docker exec "$TANG" python3 -c \
    "import urllib.request,sys;sys.stdout.write(urllib.request.urlopen('http://127.0.0.1:8099/api/state').read().decode())"
}

# jq runs in the client container (installed there with clevis-luks).
jqc() { docker exec -i "$CLIENT" jq "$@"; }

wait_running() {
  for _ in $(seq 1 60); do
    if api_state 2>/dev/null | jqc -e '.running == true' >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  fail "add-on did not report running"
}

echo "== start add-on and client"
start_tang
docker run -d --privileged --name "$CLIENT" --network "$NET" debian:trixie sleep infinity >/dev/null
docker exec "$CLIENT" sh -c 'apt-get update -qq >/dev/null && DEBIAN_FRONTEND=noninteractive \
  apt-get install -y -qq --no-install-recommends clevis clevis-luks curl jose jq cryptsetup-bin sudo >/dev/null'
wait_running

STATE=$(api_state)
SIG=$(echo "$STATE" | jqc -r '.keys[] | select(.use=="signing") | .s256')
[ -n "$SIG" ] || fail "no signing key in api/state"
CLIENT_IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$CLIENT")

echo "== clevis encrypt/decrypt through the add-on"
docker exec "$CLIENT" sh -c "echo hello | clevis encrypt tang '{\"url\":\"http://$TANG:7500\",\"thp\":\"$SIG\"}' > /hello.jwe"
OUT=$(docker exec "$CLIENT" sh -c 'clevis decrypt < /hello.jwe')
[ "$OUT" = hello ] || fail "decrypt output was '$OUT'"

echo "== request log has adv 200 and rec 200 from $CLIENT_IP"
for _ in $(seq 1 20); do
  STATE=$(api_state)
  if echo "$STATE" | jqc -e --arg ip "$CLIENT_IP" '
      any(.requests[]; .kind=="adv" and .status==200 and .ip==$ip) and
      any(.requests[]; .kind=="rec" and .status==200 and .ip==$ip)' >/dev/null; then
    break
  fi
  sleep 0.5
done
echo "$STATE" | jqc -e --arg ip "$CLIENT_IP" '
    any(.requests[]; .kind=="adv" and .status==200 and .ip==$ip) and
    any(.requests[]; .kind=="rec" and .status==200 and .ip==$ip)' >/dev/null \
  || fail "requests missing: $(echo "$STATE" | jqc -c .requests)"

echo "== JWE kid is an exchange key fingerprint"
KID=$(docker exec "$CLIENT" sh -c 'cut -d. -f1 /hello.jwe | jose b64 dec -i- | jose fmt -j- -g kid -u-')
echo "$STATE" | jqc -e --arg kid "$KID" 'any(.keys[]; .use=="exchange" and (.s256==$kid or .s1==$kid))' >/dev/null \
  || fail "kid $KID not among exchange keys: $(echo "$STATE" | jqc -c .keys)"
echo "kid $KID"

echo "== key file stems match our thumbprints"
docker exec "$TANG" python3 -c '
from pathlib import Path
from tang_monitor.keys import load_keys
keys = load_keys(Path("/data/keys"))
assert len(keys) >= 2, keys
for k in keys:
    assert k.file_stem in (k.s256, k.s1), k
    print(k.use, k.file_stem)
' || fail "key file stem does not match its thumbprint"
for stem in $(docker exec "$TANG" sh -c 'cd /data/keys && ls *.jwk' | sed 's/\.jwk$//'); do
  jwk=$(docker exec "$TANG" cat "/data/keys/$stem.jwk")
  s256=$(echo "$jwk" | docker exec -i "$CLIENT" jose jwk thp -i- -a S256)
  s1=$(echo "$jwk" | docker exec -i "$CLIENT" jose jwk thp -i- -a S1)
  echo "$STATE" | jqc -e --arg a "$s256" --arg b "$s1" 'any(.keys[]; .s256==$a and .s1==$b)' >/dev/null \
    || fail "jose thumbprints of $stem ($s256, $s1) differ from api/state keys"
done

echo "== LUKS2 one-step test script"
if LOOP=$(docker exec "$CLIENT" sh -c 'truncate -s 64M /disk.img && losetup -f --show /disk.img' 2>/dev/null) \
    && [ -n "$LOOP" ] && docker exec "$CLIENT" test -b "$LOOP"; then
  docker exec "$CLIENT" sh -c "printf %s test | cryptsetup luksFormat --type luks2 --batch-mode --key-file=- $LOOP"
  docker exec "$CLIENT" bash -c "clevis luks bind -k- -y -d $LOOP tang '{\"url\":\"http://$TANG:7500\"}' <<< test"

  # Restart the add-on (same /data, so same keys) with the commands un-hidden. The fake SUPERVISOR_TOKEN also
  # proves container env reaches the app (s6-overlay must not strip it) and that a dead Supervisor is survivable.
  docker rm -f "$TANG" >/dev/null
  start_tang -e TANG_COMMANDS_VERIFIED=1 -e SUPERVISOR_TOKEN=integration-test
  wait_running
  STATE2=$(api_state)
  [ "$(echo "$STATE2" | jqc -r '.keys[] | select(.use=="signing") | .s256')" = "$SIG" ] \
    || fail "keys changed across restart"
  SCRIPT=$(echo "$STATE2" | jqc -er '.test_commands.one_step_test') || fail "no one_step_test in api/state"
  RESULT=$(printf '%s\n' "$SCRIPT" | docker exec -i "$CLIENT" sh 2>&1) || true
  echo "$RESULT"
  echo "$RESULT" | grep -qx "OK: $LOOP slot 1" || fail "one-step script did not print 'OK: $LOOP slot 1'"
  for _ in $(seq 1 30); do
    docker logs "$TANG" 2>&1 | grep -q "Supervisor network_info failed" && break
    sleep 1
  done
  docker logs "$TANG" 2>&1 | grep -q "Supervisor network_info failed" \
    || fail "SUPERVISOR_TOKEN did not reach the app"
  api_state | jqc -e '.running == true' >/dev/null || fail "add-on unhealthy after Supervisor failures"
else
  LOOP=""
  echo "SKIP luks check"
fi

echo "INTEGRATION OK"
