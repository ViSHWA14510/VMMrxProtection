# VMMrx Bot — GitHub + Render Setup Guide

---

## 📁 GitHub Folder Structure

Your repository should look exactly like this:

```
vmmrx-bot/                   ← Root of your GitHub repo
│
├── bot.py                   ← Main bot (commands, handlers, admin logic)
├── db.py                    ← SQLite user database
├── generator.py             ← API calls to your Vercel deployment
├── requirements.txt         ← Python dependencies
├── render.yaml              ← Render auto-deploy config
├── .env.example             ← Env variable template (safe to commit)
├── .gitignore               ← Prevents secrets from being committed
└── README.md                ← Documentation
```

> ⚠️ Do NOT create any subfolders. All `.py` files must be at the root level
> so `bot.py` can import `db` and `generator` directly.

---

## 📄 .gitignore (IMPORTANT — create this file)

Create a `.gitignore` file in the root to keep secrets and junk out of GitHub:

```
# Environment secrets — NEVER commit this
.env

# SQLite database file
*.db

# Python cache
__pycache__/
*.pyc
*.pyo

# Virtual environment
venv/
.venv/
env/

# OS junk
.DS_Store
Thumbs.db
```

---

## 🐙 Step-by-Step: Push to GitHub

### Step 1 — Create repo on GitHub

1. Go to [github.com](https://github.com) → click **New repository**
2. Name it `vmmrx-bot`
3. Set to **Private** (recommended — your bot code is private)
4. Do NOT initialize with README (you already have one)
5. Click **Create repository**

---

### Step 2 — Set up your local folder

Unzip the bot files you downloaded. Your local folder should look like:

```
vmmrx-bot/
├── bot.py
├── db.py
├── generator.py
├── requirements.txt
├── render.yaml
├── .env.example
└── README.md
```

Now create the `.gitignore` file (copy from the section above).

Also create your actual `.env` file for local testing (never commit this):

```
BOT_TOKEN=your_bot_token
SITE_URL=https://your-vercel-app.vercel.app
ADMIN_KEY=your_admin_key
ADMIN_IDS=your_telegram_user_id
DB_PATH=vmmrx_bot.db
```

---

### Step 3 — Initialize Git and push

Open terminal inside the `vmmrx-bot/` folder and run:

```bash
# Initialize git
git init

# Add all files
git add .

# Check what will be committed (make sure .env is NOT listed)
git status

# Commit
git commit -m "Initial commit — VMMrx Telegram Bot"

# Connect to your GitHub repo (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/vmmrx-bot.git

# Push
git branch -M main
git push -u origin main
```

✅ Your repo is now live on GitHub.

---

## 🚀 Step-by-Step: Deploy on Render

### Step 1 — Create a Render account

Go to [render.com](https://render.com) and sign up (free tier works fine for a bot).

---

### Step 2 — Connect GitHub

1. In Render dashboard → click **New +**
2. Select **Background Worker** (not Web Service — bots don't need HTTP)
3. Click **Connect a repository**
4. Authorize Render to access your GitHub
5. Select your `vmmrx-bot` repo

---

### Step 3 — Configure the service

Render will auto-detect `render.yaml` but confirm these settings manually:

| Setting | Value |
|---|---|
| **Name** | `vmmrx-protection-bot` |
| **Region** | Closest to you (e.g. Singapore for India) |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python bot.py` |
| **Instance Type** | Free (or Starter for always-on) |

---

### Step 4 — Add Environment Variables

In Render → your service → **Environment** tab → click **Add Environment Variable** for each:

| Key | Value | Notes |
|---|---|---|
| `BOT_TOKEN` | `7123456789:AAF...` | From @BotFather on Telegram |
| `SITE_URL` | `https://vmmrx.vercel.app` | Your Vercel deployment URL |
| `ADMIN_KEY` | `your_secret_key` | Must match your Vercel `ADMIN_KEY` env var |
| `ADMIN_IDS` | `123456789` | Your Telegram user ID — get it from @userinfobot |
| `DB_PATH` | `/opt/render/project/src/vmmrx_bot.db` | Copy this exactly |

> 💡 For multiple admins: `ADMIN_IDS=123456789,987654321`

---

### Step 5 — Deploy

Click **Create Background Worker** → Render will:
1. Pull your code from GitHub
2. Run `pip install -r requirements.txt`
3. Start `python bot.py`

Watch the **Logs** tab — you should see:

```
VMMrx Bot is starting...
Application started
```

---

### Step 6 — Test your bot

1. Open Telegram → search your bot by username
2. Send `/start`
3. Since you're in `ADMIN_IDS`, you'll have full access immediately
4. Try `/lksfy`, paste a URL, verify the reply format

---

## 🔄 How to Update the Bot Later

Whenever you change any file:

```bash
git add .
git commit -m "describe your change"
git push
```

Render **auto-deploys** on every push to `main` — no manual steps needed.

---

## ⚠️ Common Issues

| Problem | Fix |
|---|---|
| Bot doesn't respond | Check `BOT_TOKEN` is correct in Render env vars |
| "API error 401" when generating links | Check `ADMIN_KEY` matches your Vercel env var exactly |
| "API error 502" on link generation | Check `SITE_URL` is correct and your Vercel app is live |
| Bot stops after ~15 min on free tier | Upgrade to Render Starter ($7/mo) for always-on |
| Admin notifications not coming | Make sure your Telegram ID is in `ADMIN_IDS` |
| DB resets on redeploy (free tier) | Upgrade to Starter — free tier has ephemeral disk |

---

## 📌 Quick Reference

```
Get your Telegram user ID  →  message @userinfobot on Telegram
Get BOT_TOKEN              →  message @BotFather on Telegram → /newbot
Get SITE_URL               →  your Vercel project dashboard URL
Get ADMIN_KEY              →  Vercel → your project → Settings → Environment Variables
```
