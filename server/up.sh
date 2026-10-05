#!/bin/sh
# Installs, builds and starts the dashboard and the extractor on a Linux server, as two services
# of your own user that start again after a reboot. No Docker and no sudo.
# Run it again after `git pull` to update. It needs .env.local in the repo root; server\send.cmd
# on the PC brings it over together with the screenshots and the unsaved drafts.
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
# Where uv and Bun install themselves. A shell started over ssh does not always have these.
PATH="$HOME/.local/bin:$HOME/.bun/bin:$HOME/.cargo/bin:$PATH"
export PATH
# systemctl --user finds the services of your user through this folder.
XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export XDG_RUNTIME_DIR

if [ ! -f .env.local ]; then
  echo ".env.local is missing. On the PC, in the project folder, run:  server\\send.cmd user@this-server"
  exit 1
fi
if ! systemctl --user show-environment >/dev/null 2>&1; then
  echo "The services run under systemd for your user, and it does not answer here."
  echo "Log in over ssh as yourself (not through su or sudo) and run this again."
  exit 1
fi

# One value of a file of NAME=value lines, without quotes and without a Windows line ending.
value() {
  sed -n "s/^$1=//p" "$2" 2>/dev/null | head -n 1 | tr -d "\"'\r"
}

url=$(value CONVEX_URL .env.local)
[ -n "$url" ] || url=$(value CONVEX_SELF_HOSTED_URL .env.local)
if [ -z "$url" ]; then
  echo ".env.local holds no CONVEX_URL and no CONVEX_SELF_HOSTED_URL."
  exit 1
fi
host=$(printf '%s' "$url" | sed -E 's#^[a-zA-Z]+://##; s#[:/].*$##')
case "$host" in
  *[!0-9.]*)
    if ! getent hosts "$host" >/dev/null 2>&1; then
      echo "This server cannot find $host. Put the address of the Convex machine in .env.local,"
      echo "for example CONVEX_SELF_HOSTED_URL=http://192.168.1.10:3810, and run this again."
      exit 1
    fi
    ;;
esac

# Ports can be set in .env in the repo root: WEB_PORT=... and EXTRACTOR_PORT=...
web_port=$(value WEB_PORT .env)
web_port=${web_port:-3000}
ext_port=$(value EXTRACTOR_PORT .env)
ext_port=${ext_port:-8787}

# A port taken by something that is not our own service, for example a copy started by hand.
busy() {
  ! systemctl --user is-active --quiet "$2" && ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$1\$"
}
if busy "$ext_port" rov-extractor; then
  echo "Port $ext_port is in use by another program. Stop it, or put EXTRACTOR_PORT=... in .env, and run this again."
  exit 1
fi
if busy "$web_port" rov-web; then
  echo "Port $web_port is in use by another program. Stop it, or put WEB_PORT=... in .env, and run this again."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv into your home folder ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v bun >/dev/null 2>&1; then
  echo "Installing Bun into your home folder ..."
  curl -fsSL https://bun.sh/install | bash
fi

echo "Extractor: installing Python packages ..."
(cd apps/extractor && uv sync --frozen --no-dev --quiet)
if ! apps/extractor/.venv/bin/python -c "import cv2" 2>/dev/null; then
  echo "OpenCV cannot load its system libraries. Run this once, then run up.sh again:"
  echo "  sudo apt-get install -y libgl1 libglib2.0-0 libxcb1"
  exit 1
fi

echo "Dashboard: installing packages and building ..."
log=${TMPDIR:-/tmp}/rov_build.log
if ! { bun install --frozen-lockfile && cd apps/web && NITRO_PRESET=bun VITE_CONVEX_URL="$url" NODE_ENV=production bun run build; } >"$log" 2>&1; then
  tail -n 40 "$log"
  echo "The dashboard did not build. The full output is in $log. If Bun is old, 'bun upgrade' may help."
  exit 1
fi
cd "$ROOT"

units=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
mkdir -p "$units" data/series
cat >"$units/rov-extractor.service" <<EOF
[Unit]
Description=RoV extractor ($ROOT)

[Service]
WorkingDirectory=$ROOT/apps/extractor
ExecStart="$ROOT/apps/extractor/.venv/bin/rov-extract" serve --lan --port $ext_port
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
cat >"$units/rov-web.service" <<EOF
[Unit]
Description=RoV dashboard ($ROOT)

[Service]
WorkingDirectory=$ROOT/apps/web
Environment=HOST=0.0.0.0 PORT=$web_port NODE_ENV=production
ExecStart="$(command -v bun)" run .output/server/index.mjs
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --quiet rov-extractor rov-web
systemctl --user restart rov-extractor rov-web
sleep 5
for unit in rov-extractor rov-web; do
  if ! systemctl --user is-active --quiet "$unit"; then
    echo "$unit did not start:"
    journalctl --user -u "$unit" -n 25 --no-pager || true
    exit 1
  fi
done

# Without lingering, the services of a user stop at logout and do not start at boot.
me=$(id -un)
loginctl --no-ask-password enable-linger "$me" >/dev/null 2>&1 || true
linger=$(loginctl show-user "$me" -p Linger 2>/dev/null | sed 's/^Linger=//')

addr=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
[ -n "$addr" ] || addr=$(hostname)
echo
echo "Dashboard: http://$addr:$web_port"
echo "Extractor: http://$addr:$ext_port"
if [ "$linger" != yes ]; then
  echo
  echo "One step is left, and it needs sudo once. Without it both stop when you log out:"
  echo "  sudo loginctl enable-linger $me"
fi
