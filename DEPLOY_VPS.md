# Deploying VMMrx Protection Bot on a VPS (from your GitHub repo)

Works on any Ubuntu/Debian VPS (DigitalOcean, Hetzner, Contabo, AWS EC2, etc).

## 1. Push these files to your GitHub repo

Make sure `deploy.sh`, `update.sh`, `vmmrx-bot.service`, and the updated
`bot.py`/`requirements.txt` (with `python-dotenv` support) are committed
and pushed to your repo. `.env` is already git-ignored — never commit it.

## 2. SSH into your VPS and run the deploy script

```bash
curl -o deploy.sh https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main/deploy.sh
sudo bash deploy.sh https://github.com/YOUR_USER/YOUR_REPO.git
```

(Or clone the repo first and run `sudo bash deploy.sh <repo-url>` from inside it — either works, the script clones fresh into `/opt/vmmrx-bot`.)

This will:
- Install Python 3, venv, and git
- Create a dedicated, unprivileged `vmmrxbot` system user
- Clone your repo into `/opt/vmmrx-bot`
- Create a virtual environment and install dependencies
- Copy `.env.example` → `.env` (if `.env` doesn't already exist)
- Install and enable a `systemd` service (`vmmrx-bot`) so the bot
  auto-starts on boot and restarts if it crashes

## 3. Configure your bot

```bash
sudo nano /opt/vmmrx-bot/.env
```

Fill in at minimum:
- `BOT_TOKEN` — from @BotFather
- `WORKER_URL` — your Cloudflare Worker URL
- `ADMIN_SECRET` — matches your `wrangler secret put ADMIN_SECRET`
- `ADMIN_IDS` — your Telegram numeric user ID(s), comma separated

## 4. Start the bot

```bash
sudo systemctl restart vmmrx-bot
sudo systemctl status vmmrx-bot
```

## 5. Useful commands

| Action              | Command                                   |
|---------------------|--------------------------------------------|
| View live logs      | `sudo journalctl -u vmmrx-bot -f`          |
| Restart the bot     | `sudo systemctl restart vmmrx-bot`         |
| Stop the bot        | `sudo systemctl stop vmmrx-bot`            |
| Disable autostart   | `sudo systemctl disable vmmrx-bot`         |

## 6. Updating the bot later (after you push new commits to GitHub)

```bash
cd /opt/vmmrx-bot
sudo bash update.sh
```

This pulls the latest commit, reinstalls any new dependencies, and
restarts the service. `.env` and the SQLite DB are untouched since
they're git-ignored and stay local to the server.

## Notes

- The bot uses **long polling** (not webhooks), so no domain, SSL
  certificate, or open inbound port is required — it just needs
  outbound internet access to reach `api.telegram.org`.
- The SQLite database file lives at `/opt/vmmrx-bot/vmmrx_bot.db` by
  default. Back it up periodically:
  `sudo cp /opt/vmmrx-bot/vmmrx_bot.db ~/vmmrx_bot.db.bak`
- If your repo is **private**, `git clone`/`git pull` on the VPS will
  need credentials — either use a GitHub Personal Access Token in the
  clone URL (`https://TOKEN@github.com/you/repo.git`) or set up a
  deploy key via SSH.
- `Procfile`, `railway.json`, and `runtime.txt` from the original
  package were removed — those are Railway/Heroku-specific and are
  not used on a plain VPS with systemd.

