#!/bin/sh
# Builds and starts the dashboard and the extractor on a Linux server that has Docker.
# Run it again after `git pull` to update. It needs .env.local in the repo root; server\send.cmd
# on the PC brings it over together with the screenshots and the hero art.
set -eu
cd "$(dirname "$0")/.."

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker with the compose plugin is needed and was not found."
  exit 1
fi
if [ ! -f .env.local ]; then
  echo ".env.local is missing. On the PC, in the project folder, run:  server\\send.cmd user@this-server"
  exit 1
fi

# One value of .env.local, without quotes and without a Windows line ending.
value() {
  sed -n "s/^$1=//p" .env.local | head -n 1 | tr -d "\"'\r"
}

url=$(value CONVEX_URL)
[ -n "$url" ] || url=$(value CONVEX_SELF_HOSTED_URL)
if [ -z "$url" ]; then
  echo ".env.local holds no CONVEX_URL and no CONVEX_SELF_HOSTED_URL."
  exit 1
fi

# A name of the home network (suwinas.local, or a bare name) means nothing inside a container.
# Find its address here. When the name is this machine itself, the containers go through the host.
host=$(printf '%s' "$url" | sed -E 's#^[a-zA-Z]+://##; s#[:/].*$##')
pin_host=convex.invalid
pin_ip=127.0.0.1
case "$host" in
  *.local) lan=1 ;;
  *[!0-9.]*.*) lan=0 ;;  # a name with a dot: ordinary DNS, a container finds it itself
  *[!0-9.]*) lan=1 ;;    # a bare name
  *) lan=0 ;;            # an address
esac
if [ "$lan" = 1 ]; then
  ip=$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1 {print $1}' || true)
  [ -n "$ip" ] || ip=$(avahi-resolve -4 -n "$host" 2>/dev/null | awk 'NR==1 {print $2}' || true)
  [ -n "$ip" ] || ip=$(ping -c 1 -W 2 "$host" 2>/dev/null | sed -n '1s/^[^(]*(\([0-9.]*\)).*/\1/p' || true)
  if [ -z "$ip" ]; then
    echo "This server cannot find $host. Put the address of the Convex machine in .env.local,"
    echo "for example CONVEX_SELF_HOSTED_URL=http://192.168.1.10:3810, and run this again."
    exit 1
  fi
  case "$ip" in
    127.*) ip=host-gateway ;;
  esac
  pin_host=$host
  pin_ip=$ip
fi

# Ports chosen by hand in .env survive; the rest is written fresh.
keep=$(grep -E '^(WEB_PORT|EXTRACTOR_PORT)=' .env 2>/dev/null || true)
{
  echo "# Written by server/up.sh. Only WEB_PORT and EXTRACTOR_PORT are kept when it runs again."
  echo "VITE_CONVEX_URL=$url"
  echo "CONVEX_HOST=$pin_host"
  echo "CONVEX_IP=$pin_ip"
  echo "ROV_UID=$(id -u)"
  echo "ROV_GID=$(id -g)"
  [ -z "$keep" ] || echo "$keep"
} > .env

mkdir -p data/series
docker compose up -d --build --remove-orphans

web_port=$(sed -n 's/^WEB_PORT=//p' .env | head -n 1)
ext_port=$(sed -n 's/^EXTRACTOR_PORT=//p' .env | head -n 1)
addr=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
[ -n "$addr" ] || addr=$(hostname)
echo
echo "Dashboard: http://$addr:${web_port:-3000}"
echo "Extractor: http://$addr:${ext_port:-8787}"
