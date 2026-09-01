#!/usr/bin/env bash
# One-command demo startup. PLAN.MD section 36 (Phase 8).
#
#   ./run_demo.sh              start server only (the OpenAI tunnel reaches it
#                              over loopback, so nothing else is needed)
#   ./run_demo.sh --ngrok      also open an ngrok tunnel, as a fallback
#
# The demo connects through the OpenAI MCP control-plane tunnel:
#
#   tunnel-client run --profile smartpay
#
# configured at https://platform.openai.com/settings/organization/tunnels and
# pointed at http://127.0.0.1:<PORT>/mcp. Because tunnel-client dials loopback,
# the Host header is already allowed and SMARTPAY_PUBLIC_HOST is NOT required.
# It is only needed for a tunnel that forwards its own public hostname (ngrok,
# Cloudflare); without it there, /mcp returns 421 while /health returns 200.
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${SMARTPAY_PORT:-9022}"
VENV=".venv/bin/python"

if [[ ! -x "$VENV" ]]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi

if [[ ! -f data/alex/transactions.json ]]; then
  echo "Generating Alex's dataset..."
  $VENV scripts/generate_alex.py
fi

echo "Verifying the frozen demo numbers..."
$VENV -m pytest tests/ -q

cleanup() { kill $(jobs -p) 2>/dev/null || true; }
trap cleanup EXIT

if [[ "${1:-}" != "--ngrok" ]]; then
  cat <<BANNER

  SmartPay is live on http://127.0.0.1:${PORT}/mcp

  If the OpenAI tunnel is running (tunnel-client run --profile smartpay) it will
  reach this over loopback and ChatGPT can call the tools. Check it with:

      curl -s http://127.0.0.1:8080/readyz

BANNER
  exec $VENV -m app.mcp_server
fi

if ! command -v ngrok >/dev/null; then
  echo "ngrok not found. Run with --local, or install ngrok." >&2
  exit 1
fi

ngrok http "$PORT" --log stdout --log-format json > /tmp/smartpay-ngrok.log 2>&1 &

PUBLIC_URL=""
for _ in $(seq 1 30); do
  PUBLIC_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["tunnels"][0]["public_url"])' 2>/dev/null || true)
  [[ -n "$PUBLIC_URL" ]] && break
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "Could not read the ngrok URL. See /tmp/smartpay-ngrok.log" >&2
  exit 1
fi

# The MCP SDK rejects any Host header it was not told about, and it does not
# support subdomain wildcards, so the tunnel hostname must be passed explicitly.
# Without this, /health returns 200 while /mcp returns 421 -- which looks healthy
# and is not.
export SMARTPAY_PUBLIC_HOST="${PUBLIC_URL#https://}"

cat <<BANNER

  SmartPay is live.

    ChatGPT connector URL : ${PUBLIC_URL}/mcp
    Health                : ${PUBLIC_URL}/health
    Local                 : http://127.0.0.1:${PORT}/mcp

  Register the connector URL in ChatGPT (Settings > Connectors > Developer mode).
  This ngrok dev domain is stable across restarts, so you only do that once.

BANNER

exec $VENV -m app.mcp_server
