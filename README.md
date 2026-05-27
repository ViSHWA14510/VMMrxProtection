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
├── generator.py      # API calls to your Vercel deployment
├── requirements.txt  # Python dependencies
├── render.yaml       # Render deployment config
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

## 🚀 Deploy on Render

### Step 1 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial bot commit"
git remote add origin https://github.com/YOUR_USERNAME/vmmrx-bot.git
git push -u origin main
```

### Step 2 — Create Render Worker

1. Go to [render.com](https://render.com) → **New** → **Background Worker**
2. Connect your GitHub repo
3. Render auto-detects `render.yaml` — confirm settings:
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`

### Step 3 — Add Environment Variables

In Render dashboard → your service → **Environment**:

```
BOT_TOKEN     = <from @BotFather>
SITE_URL      = https://your-vercel-app.vercel.app
ADMIN_KEY     = <your Vercel ADMIN_KEY>
ADMIN_IDS     = <your Telegram user ID>
DB_PATH       = /opt/render/project/src/vmmrx_bot.db
```

> 💡 Get your Telegram user ID by messaging [@userinfobot](https://t.me/userinfobot)

### Step 4 — Deploy

Click **Deploy** — your bot will be live in ~2 minutes.

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
