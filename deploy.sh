#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# VMMrx Protection Bot — VPS deploy script (Ubuntu/Debian)
# Pulls the bot straight from your GitHub repo.
#
# Usage:
#   sudo bash deploy.sh https://github.com/yourname/yourrepo.git
#
# (or edit REPO_URL below and just run: sudo bash deploy.sh)
# ─────────────────────────────────────────────────────────────────
set -e

REPO_URL="${1:-https://github.com/yourname/yourrepo.git}"
APP_DIR="/opt/vmmrx-bot"
SERVICE_USER="vmmrxbot"
SERVICE_NAME="vmmrx-bot"

if [ "$REPO_URL" = "https://github.com/yourname/yourrepo.git" ]; then
    echo "ERROR: Set your repo URL — either pass it as an argument:"
    echo "  sudo bash deploy.sh https://github.com/yourname/yourrepo.git"
    echo "or edit REPO_URL at the top of this script."
    exit 1
fi

echo "==> Installing system dependencies..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git

echo "==> Creating service user (if not exists)..."
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if [ -d "$APP_DIR/.git" ]; then
    echo "==> Existing install found — pulling latest changes..."
    cd "$APP_DIR"
    sudo -u "$SERVICE_USER" git pull
else
    echo "==> Cloning $REPO_URL into $APP_DIR ..."
    rm -rf "$APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$APP_DIR/.env.example" ]; then
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        echo "==> Created .env from .env.example — EDIT IT NOW with your real values:"
        echo "    nano $APP_DIR/.env"
    fi
fi

echo "==> Creating/updating Python virtual environment..."
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Setting file ownership..."
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env" || true

echo "==> Installing systemd service..."
cp "$APP_DIR/vmmrx-bot.service" /etc/systemd/system/"$SERVICE_NAME".service
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "─────────────────────────────────────────────────────────"
echo " Setup complete!"
echo ""
echo " 1. Edit your config:   nano $APP_DIR/.env"
echo " 2. Start the bot:      sudo systemctl restart $SERVICE_NAME"
echo " 3. Check status:       sudo systemctl status $SERVICE_NAME"
echo " 4. View live logs:     sudo journalctl -u $SERVICE_NAME -f"
echo "─────────────────────────────────────────────────────────"
