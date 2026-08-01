#!/usr/bin/env bash
# Pull the latest code from GitHub and restart the bot.
# Run on the VPS: sudo bash update.sh
set -e

APP_DIR="/opt/vmmrx-bot"
SERVICE_USER="vmmrxbot"
SERVICE_NAME="vmmrx-bot"

cd "$APP_DIR"
echo "==> Pulling latest changes..."
sudo -u "$SERVICE_USER" git pull

echo "==> Updating dependencies..."
./venv/bin/pip install -r requirements.txt

echo "==> Restarting service..."
systemctl restart "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager

echo "==> Done. Tail logs with: sudo journalctl -u $SERVICE_NAME -f"
