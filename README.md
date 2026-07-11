# VMMrx Protection Bot 🤖🛡️

Telegram bot for generating Cloudflare-protected links from your VMMrx Protection deployment.  
Supports lksfy shortening, direct Cloudflare protection, bulk mode, and admin-based user authorization.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔗 **lksfy + Protect mode** | Shortens link via lksfy, then wraps in Cloudflare protection |
| 🛡️ **Direct Protect mode** | Wraps original link in Cloudflare protection only |
| 📦 **Bulk mode** | Paste multiple URLs (one per line) — all processed at once |
| 👑 **Admin authorization** | Only admin-approved users can generate links |
| 🔔 **Approval notifications** | Admins get notified instantly when a new user joins |
| ✅ **Inline approve/deny** | Approve or deny users directly from the Telegram notification |

---

## 📁 File Structure

```
vmmrx-bot/
├── bot.py            # Main bot logic, commands, handlers
├── db.py             # SQLite user database (auth, pending, approved)
├── generator.py      # API calls to your Cloudflare Worker
├── requirements.txt  # Python dependencies
├── Procfile          # Process type for Railway/Heroku-style platforms
├── railway.json      # Railway build/deploy config
├── runtime.txt       # Pinned Python version
└── .env.example      # Environment variable template
```

---

## ⚙️ Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `SITE_URL` | ✅ | Your Vercel deployment URL (e.g. `https://vmmrx.vercel.app`) |
| `ADMIN_KEY` | ✅ | Your Vercel `ADMIN_KEY` env var value |
| `ADMIN_IDS` | ✅ | Comma-separated Telegram user IDs of bot admins |
| `DB_PATH` | ❌ | SQLite file path (auto-set on Render) |

---

## 🚀 Deploy on Railway

### Step 1 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial bot commit"
git remote add origin https://github.com/YOUR_USERNAME/vmmrx-bot.git
git push -u origin main
```

### Step 2 — Create a Railway project

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select your repo. Railway auto-detects Python via `requirements.txt` and reads
   the included `railway.json` / `Procfile`, so no manual build/start command setup is needed.
3. Since this bot uses long-polling (no web server), Railway will treat it as a
   **worker service** — you don't need to expose a public port.

### Step 3 — Add Environment Variables

In your Railway service → **Variables** tab, add:

```
BOT_TOKEN          = <from @BotFather>
WORKER_URL         = https://your-worker.workers.dev
ADMIN_SECRET       = <your Cloudflare Worker ADMIN_SECRET>
ADMIN_IDS          = <comma-separated Telegram user IDs>
FORCE_SUB_CHANNEL  = @yourchannel        (optional)
BANNER_IMAGE_URL   = https://...          (optional)
BOT_NAME           = VMMrx Protection     (optional)
MAINTAINER_NAME    = VMMrx Developer      (optional)
UPDATES_URL        = https://t.me/...     (optional)
SUPPORT_URL        = https://t.me/...     (optional)
CARD_IMAGES        = https://img1,https://img2  (optional)
```

> 💡 Get your Telegram user ID by messaging [@userinfobot](https://t.me/userinfobot)

### Step 4 — (Recommended) Add a persistent Volume for the SQLite DB

Railway's filesystem is ephemeral across redeploys. To keep your approved-user
and sites data across deploys:

1. In your service → **Settings** → **Volumes** → **Add Volume**
2. Mount path: `/data`
3. Add an environment variable: `DB_PATH=/data/vmmrx_bot.db`

Without a volume, the bot still works — the DB just resets on the next deploy.

### Step 5 — Deploy

Railway deploys automatically on push. Check the **Deploy Logs** tab — you should see:
```
VMMrx Bot is starting...
```

---



## 🤖 Bot Commands

### User Commands
| Command | Description |
|---|---|
| `/start` | Welcome message + request access |
| `/lksfy` | Switch to lksfy + Cloudflare protect mode |
| `/direct` | Switch to direct Cloudflare protect mode |
| `/mode` | Show current active mode |
| `/help` | Detailed help guide |

### Admin Commands
| Command | Description |
|---|---|
| `/pending` | List users waiting for approval |
| `/approve <user_id>` | Approve a user |
| `/revoke <user_id>` | Revoke a user's access |
| `/users` | List all approved users |

---

## 🔐 Authorization Flow

```
User sends /start
       │
       ▼
Is user admin? ──YES──▶ Full access immediately
       │
       NO
       ▼
Is user approved? ──YES──▶ Full access
       │
       NO
       ▼
Mark as pending + notify all admins
       │
       ▼
Admin taps [✅ Approve] or [❌ Deny]
       │
       ▼
User gets notified of the decision
```

---

## 📦 Bulk Mode Example

After selecting a mode, paste multiple URLs:

```
https://example.com/page1
https://example.com/page2
https://example.com/page3
```

Bot will process all at once and return a consolidated result.

---

## 🛠 Local Testing

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in your .env values
python bot.py
```
