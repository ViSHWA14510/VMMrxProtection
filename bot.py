"""
VMMrx Protection Bot — Telegram bot for generating protected links.
Direct (Cloudflare-only) mode, bulk generation, admin-based user
authorization, and force subscribe.
"""

import os
import sys
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from db import (
    is_approved,
    is_admin,
    approve_user,
    revoke_user,
    get_pending_users,
    add_pending_user,
    get_all_users,
    get_user_info,
    save_user,
    add_site,
    get_sites,
    get_site,
    get_default_site,
    delete_site,
    increment_site_links,
)
from generator import generate_direct_link, generate_protected_link

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
FORCE_SUB_CHANNEL = os.environ.get("FORCE_SUB_CHANNEL", "")  # e.g. @yourchannel

# ── /start screen branding ───────────────────────────────────────────────────
BANNER_IMAGE_URL = os.environ.get("BANNER_IMAGE_URL", "")  # banner shown above the welcome text
BOT_NAME          = os.environ.get("BOT_NAME", "VMMrx Protection")
MAINTAINER_NAME   = os.environ.get("MAINTAINER_NAME", "VMMrx Developer")
UPDATES_URL       = os.environ.get("UPDATES_URL", "https://t.me/your_updates_channel")
SUPPORT_URL       = os.environ.get("SUPPORT_URL", "https://t.me/your_support_group")
DASHBOARD_URL     = os.environ.get("DASHBOARD_URL", "")  # leave empty until a real dashboard exists

# ── Protected-link card banner ────────────────────────────────────────────────
# Comma-separated list of image URLs — one is picked at random for each
# "Link Protected Successfully" card. Falls back to a random photo service
# (picsum.photos) when unset, so a different image shows every time.
_CARD_IMAGES_RAW = os.environ.get("CARD_IMAGES", "")
CARD_IMAGES = [u.strip() for u in _CARD_IMAGES_RAW.split(",") if u.strip()]

def pick_card_image() -> str:
    if CARD_IMAGES:
        return random.choice(CARD_IMAGES)
    return f"https://picsum.photos/seed/{random.randint(1, 1_000_000)}/700/400"

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_urls(text: str) -> list[str]:
    """Extract all valid http/https URLs from text (one per line or space-sep)."""
    urls = []
    for word in text.replace("\n", " ").split():
        word = word.strip()
        if word.startswith("http://") or word.startswith("https://"):
            urls.append(word)
    return urls

def escape(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

# ── Small-caps unicode text style (used on link protection cards) ────────────
_SMALLCAPS_MAP = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ",
    "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
    "o": "ᴏ", "p": "ᴘ", "q": "Q", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ",
    "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
}

def smallcaps(text: str) -> str:
    """Convert a string to small-caps unicode style (letters only; digits,
    punctuation, and spacing are left untouched)."""
    return "".join(_SMALLCAPS_MAP.get(ch.lower(), ch) for ch in text)

# ── UI constants ──────────────────────────────────────────────────────────────
DIVIDER = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

# ── Shared screen builders (keep /start, /help, and their button versions
#    perfectly in sync so the UI never drifts between screens) ────────────────

def build_welcome_text(user, context: ContextTypes.DEFAULT_TYPE) -> str:
    first_name = escape(user.first_name or "there")
    bot_name = escape(BOT_NAME.upper())
    maintainer = escape(MAINTAINER_NAME)

    lines = [
        f"👋 Hello *{first_name}*,",
        "",
        f"🚀 Welcome to *{bot_name}*",
        "",
        "🔒 *The ultimate link protection system*",
        "Secure your links and block all bypass attempts instantly with our advanced security layers\\.",
        "",
        "✨ *Core features:*",
        "🛡️ Advanced anti\\-bypass shield",
        "⚡ Lightning fast \\& seamless UX",
        "📦 Bulk link processing",
    ]

    if is_admin(user.id):
        lines += [
            "",
            "👑 *Admin Panel:*",
            "  `/pending`        View users awaiting approval",
            "  `/approve id`  Approve a user",
            "  `/revoke id`    Revoke a user's access",
            "  `/users`          List all approved users",
            "  `/restart`        Restart the bot",
        ]

    lines += [
        "",
        f"Maintained by: {maintainer}",
        "",
    ]

    if is_approved(user.id):
        lines.append("✅ *Account approved — just send a link to get started\\!*")
    else:
        lines.append("⏳ *Awaiting admin approval\\.* You'll be notified the moment you're approved\\.")

    return "\n".join(lines)

def build_home_keyboard(user) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📣 Updates", url=UPDATES_URL),
            InlineKeyboardButton("💬 Support", url=SUPPORT_URL),
        ],
    ]
    if DASHBOARD_URL:
        rows.append([InlineKeyboardButton("⚙️ Dashboard", url=DASHBOARD_URL)])
    else:
        rows.append([InlineKeyboardButton("⚙️ Dashboard", callback_data="show_dashboard")])
    rows.append([
        InlineKeyboardButton("ℹ️ Help", callback_data="show_help"),
        InlineKeyboardButton("👤 About", callback_data="show_about"),
    ])
    return InlineKeyboardMarkup(rows)

def build_help_text() -> str:
    return "\n".join([
        "📖 *Help & Guide*",
        DIVIDER,
        "*🛡️ Direct Protect*",
        "Send any link and I'll wrap it in Cloudflare protection\\.",
        "You get: `Original` → `Protected link`",
        "",
        "*📦 Bulk Mode*",
        "Paste multiple URLs \\(one per line\\) — all are processed together\\.",
        "",
        DIVIDER,
        "*📌 Quick Start*",
        "1️⃣ Paste one or more links",
        "2️⃣ Get your protected link\\(s\\) instantly ⚡",
    ])

def build_about_text() -> str:
    return "\n".join([
        "👤 *About*",
        DIVIDER,
        f"🤖 Bot        →  *{escape(BOT_NAME)}*",
        f"👑 Maintainer →  *{escape(MAINTAINER_NAME)}*",
        "🛡️ Purpose    →  Cloudflare\\-backed link protection",
    ])

def build_dashboard_text() -> str:
    return "\n".join([
        "🖥️ *Dashboard*",
        "🔧 Manage your links and system",
        "",
        "Access all premium features and control your protected links from here:",
        "",
        "🌐 Manage supported sites",
        "📊 View statistics \\& performance",
        "🕓 Track your activity",
        "🤖 Access developer API",
        "",
        "Everything you need in one place\\.",
    ])

def build_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Sites", callback_data="dash_sites"),
            InlineKeyboardButton("📊 Statistics", callback_data="dash_stats"),
        ],
        [
            InlineKeyboardButton("🛡️ Security", callback_data="dash_security"),
            InlineKeyboardButton("🕓 History", callback_data="dash_history"),
        ],
        [
            InlineKeyboardButton("📋 Logs", callback_data="dash_logs"),
            InlineKeyboardButton("⚙️ Settings", callback_data="dash_settings"),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="go_home")],
    ])

DASHBOARD_SECTIONS = {
    "dash_stats":    ("📊 Statistics", "See link performance, click counts, and usage trends\\."),
    "dash_security": ("🛡️ Security",   "Review anti\\-bypass shield status and security settings\\."),
    "dash_history":  ("🕓 History",    "Track your recent activity and generated links\\."),
    "dash_logs":     ("📋 Logs",       "Inspect detailed system and request logs\\."),
    "dash_settings": ("⚙️ Settings",   "Configure your account and bot preferences\\."),
}

def build_dashboard_section_text(key: str) -> str:
    title, desc = DASHBOARD_SECTIONS[key]
    return "\n".join([
        f"{title}",
        DIVIDER,
        desc,
        "",
        "🚧 *Coming soon\\.*",
    ])

def build_dashboard_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Dashboard", callback_data="show_dashboard")],
    ])

# ── Sites Manager ─────────────────────────────────────────────────────────────

def site_display_name(domain: str) -> str:
    """Derive a friendly display name from a site's domain, e.g.
    'https://arolinks.com' -> 'Arolinks'."""
    name = domain.replace("https://", "").replace("http://", "").split("/")[0]
    name = name.split(".")[0]
    return name.capitalize() if name else domain

def build_sites_text(sites: list[dict]) -> str:
    lines = [
        "🌐 *Sites Manager*",
        "",
        "Send a URL to add a new site\\. Your link will be automatically secured with anti\\-bypass protection\\.",
        "",
    ]
    if sites:
        lines += ["📁 *Your sites:*", "Select a site below to view details\\."]
    else:
        lines += ["📁 *Your sites:*", "You haven't added any sites yet\\."]
    lines += [
        "",
        "⚠️ Click on a site name to view details and access developer API\\.",
    ]
    return "\n".join(lines)

def build_sites_keyboard(sites: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, s in enumerate(sites, 1):
        label = f"🔗 {i}. {site_display_name(s['domain'])}"
        rows.append([InlineKeyboardButton(label, callback_data=f"site_view:{s['id']}")])
    rows.append([InlineKeyboardButton("➕ Add Shortener", callback_data="site_add")])
    rows.append([InlineKeyboardButton("🖥️ Back to Dashboard", callback_data="show_dashboard")])
    return InlineKeyboardMarkup(rows)

def clean_domain_display(domain: str) -> str:
    """Strip scheme for display, e.g. 'https://arolinks.com' -> 'arolinks.com'."""
    return domain.replace("https://", "").replace("http://", "").rstrip("/")

def build_site_detail_text(site: dict) -> str:
    name = site_display_name(site["domain"])
    domain_display = clean_domain_display(site["domain"])
    added_on = (site.get("created_at") or "").replace("T", " ")
    links_count = site.get("links_count", 0)
    return "\n".join([
        "🌐 *Site Details*",
        DIVIDER,
        "📄 Information about your selected site:",
        "",
        "🏷️ *Name*",
        escape(name),
        "🔗 *URL*",
        escape(domain_display),
        "🔑 *API Key*",
        escape(site["api_key"]),
        "📅 *Added On*",
        escape(added_on),
        "📊 *Total Links Created*",
        str(links_count),
        "",
        "🟢 *Status: Active \\& Protected*",
    ])

def build_site_detail_keyboard(site_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Developer API", callback_data=f"site_devapi:{site_id}"),
            InlineKeyboardButton("🗑️ Delete Site", callback_data=f"site_delete:{site_id}"),
        ],
        [InlineKeyboardButton("◀️ Back to Sites", callback_data="dash_sites")],
    ])

def build_site_devapi_text(site: dict) -> str:
    domain_display = clean_domain_display(site["domain"])
    return "\n".join([
        "🤖 *Developer API*",
        DIVIDER,
        f"🌐 Site → *{escape(site_display_name(site['domain']))}*",
        "",
        "Use this endpoint to shorten a link with your key:",
        f"`https://{escape(domain_display)}/api?api={escape(site['api_key'])}&url=YOUR_URL&format=json`",
        "",
        "This site is used automatically to shorten your links before Cloudflare protection\\.",
    ])

def build_site_devapi_keyboard(site_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Site", callback_data=f"site_view:{site_id}")],
    ])

# ── "Link Protected Successfully" card (single-link flow) ──────────────────

def _truncate_url(url: str, limit: int = 55) -> str:
    return url if len(url) <= limit else url[:limit].rstrip() + "..."

def build_link_card_text(user, site_name: str, original_url: str, secure_url: str, removed: bool = False) -> str:
    first_name = escape(user.first_name or "there")
    sc = lambda s: escape(smallcaps(s))
    lines = [
        f"✅ *{sc('Link Protected Successfully!')}*" if not removed else f"🗑️ *{sc('Link Removed')}*",
        "",
        f"👤 *{sc('User:')}* {first_name}",
        f"🌐 *{sc('Site:')}* {escape(site_name)}",
        "",
        f"🔗 *{sc('Original Link:')}*",
        escape(_truncate_url(original_url)),
        "",
        f"🛡️ *{sc('Secure Link:')}*",
        escape(secure_url) if not removed else f"~{sc('this link has been removed')}~",
        "",
        f"💡 _{sc('This link is fully protected against bypassers.')}_" if not removed
            else f"💡 _{sc('This link is no longer active.')}_",
    ]
    return "\n".join(lines)

def build_link_card_keyboard(secure_url: str, link_id: str | None = None) -> InlineKeyboardMarkup:
    # NOTE: the Vercel backend (api/direct.js + Upstash Redis) has no delete
    # endpoint, so protected links are permanent — no "Remove Link" button.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 View Link", url=secure_url)],
    ])

async def _edit_screen(query, text: str, keyboard: InlineKeyboardMarkup):
    """Edit the caption if the message is a photo (banner), otherwise edit the text."""
    if query.message.photo:
        await query.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )
    else:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )

# ── Force Subscribe ───────────────────────────────────────────────────────────

async def is_subscribed(bot, user_id: int) -> bool:
    """Returns True if user is member of FORCE_SUB_CHANNEL or no channel is set."""
    if not FORCE_SUB_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def send_force_sub_message(update: Update):
    """Send join prompt with inline buttons."""
    channel = FORCE_SUB_CHANNEL
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel.lstrip('@')}")],
        [InlineKeyboardButton("✅ I've Joined", callback_data="check_sub")],
    ])
    text = "\n".join([
        "🔒 *One Quick Step*",
        DIVIDER,
        "Join our channel to unlock the bot\\.",
        f"👉 {escape(channel)}",
        "",
        "Tap *✅ I've Joined* once you're in\\.",
    ])
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )

# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username or "", user.full_name or "")

    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return

    if not is_approved(user.id):
        add_pending_user(user.id, user.username or "", user.full_name or "")
        await notify_admins_new_user(context, user)

    caption = build_welcome_text(user, context)
    keyboard = build_home_keyboard(user)

    if BANNER_IMAGE_URL:
        try:
            await update.message.reply_photo(
                photo=BANNER_IMAGE_URL,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
            )
            return
        except Exception as e:
            log.warning(f"Could not send banner image: {e}")

    await update.message.reply_text(
        caption,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )

# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return

    await update.message.reply_text(build_help_text(), parse_mode=ParseMode.MARKDOWN_V2)

# ── /cancel ───────────────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    had_pending = bool(context.user_data.get("awaiting_site"))
    context.user_data.pop("awaiting_site", None)
    context.user_data.pop("pending_site_domain", None)

    if not had_pending:
        await update.message.reply_text("Nothing to cancel\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    sites = get_sites(user.id)
    await update.message.reply_text("❌ *Cancelled\\.*", parse_mode=ParseMode.MARKDOWN_V2)
    await update.message.reply_text(
        build_sites_text(sites),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=build_sites_keyboard(sites),
    )

# ── Message handler (URL processing) ─────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username or "", user.full_name or "")

    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return

    if not is_approved(user.id):
        await update.message.reply_text(
            "\n".join([
                "⏳ *Pending Approval*",
                DIVIDER,
                "Your account is awaiting admin approval\\.",
                "You'll be notified the moment you're approved\\.",
            ]),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        add_pending_user(user.id, user.username or "", user.full_name or "")
        await notify_admins_new_user(context, user)
        return

    # ── Waiting for a /site domain or API key? Handle that first. ──
    awaiting = context.user_data.get("awaiting_site")
    if awaiting:
        value = (update.message.text or "").strip()

        if awaiting == "domain":
            candidate = value
            if not (candidate.startswith("http://") or candidate.startswith("https://")):
                candidate = f"https://{candidate}"
            # crude sanity check: needs a dot and no spaces to look like a domain
            host = candidate.split("://", 1)[-1]
            if " " in value or "." not in host:
                await update.message.reply_text(
                    "\n".join([
                        "❌ *That doesn't look like a valid domain\\.*",
                        "Send it again \\(e\\.g\\., `arolinks.com`\\)\\.",
                        "",
                        "_/cancel \\- to cancel this process\\._",
                    ]),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return
            context.user_data["pending_site_domain"] = candidate.rstrip("/")
            context.user_data["awaiting_site"] = "api"
            site_name = site_display_name(candidate)
            await update.message.reply_text(
                "\n".join([
                    f"🔑 *Send me API key for:* {escape(site_name)}",
                    "",
                    "_/cancel \\- to cancel this process\\._",
                ]),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        elif awaiting == "api":
            domain = context.user_data.pop("pending_site_domain", "")
            context.user_data.pop("awaiting_site", None)
            if not domain:
                await update.message.reply_text("❌ Something went wrong — please tap *➕ Add Shortener* again\\.", parse_mode=ParseMode.MARKDOWN_V2)
                return
            add_site(user.id, domain, value)
            sites = get_sites(user.id)
            await update.message.reply_text("✅ *Shortener site added\\!*", parse_mode=ParseMode.MARKDOWN_V2)
            await update.message.reply_text(
                build_sites_text(sites),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=build_sites_keyboard(sites),
            )
            return

    text = update.message.text or ""
    urls = extract_urls(text)

    if not urls:
        await update.message.reply_text(
            "❌ *No valid URLs found\\.* Please send links starting with `http://` or `https://`\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    processing_msg = await update.message.reply_text(
        f"⚙️ Processing *{len(urls)}* link{'s' if len(urls) > 1 else ''}\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    site = get_default_site(user.id)

    # ── Single link: rich "Link Protected Successfully" card ──────────────────
    if len(urls) == 1:
        url = urls[0]
        try:
            data = await generate_protected_link(url, site)
            if site:
                increment_site_links(site["id"])
        except Exception as e:
            log.warning(f"Error processing {url}: {e}")
            await processing_msg.delete()
            await update.message.reply_text(
                "\n".join([
                    f"❌ *Failed:* `{escape(url)}`",
                    f"⚠️ {escape(str(e))}",
                ]),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        await processing_msg.delete()
        secure_url = data.get("short_protected_url") or data["protected_url"]
        site_name = site_display_name(site["domain"]) if site else "Direct Protect"
        caption = build_link_card_text(user, site_name, url, secure_url)
        keyboard = build_link_card_keyboard(secure_url, data["id"])
        try:
            await update.message.reply_photo(
                photo=pick_card_image(),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
            )
        except Exception as e:
            log.warning(f"Could not send link card image: {e}")
            await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
        return

    # ── Bulk: generate a protected link + individual card for every URL ────────
    # (same "Link Protected Successfully" card as single-link mode, one per link)

    errors = []
    site_name = site_display_name(site["domain"]) if site else "Direct Protect"

    for i, url in enumerate(urls, 1):
        try:
            data = await generate_protected_link(url, site)
            if site:
                increment_site_links(site["id"])
        except Exception as e:
            log.warning(f"Error processing {url}: {e}")
            errors.append({"index": i, "url": url, "error": str(e)})
            continue

        secure_url = data.get("short_protected_url") or data["protected_url"]
        caption = build_link_card_text(user, site_name, url, secure_url)
        keyboard = build_link_card_keyboard(secure_url, data["id"])
        try:
            await update.message.reply_photo(
                photo=pick_card_image(),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
            )
        except Exception as e:
            log.warning(f"Could not send link card image: {e}")
            await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)

    await processing_msg.delete()

    # Report any errors separately
    for e in errors:
        await update.message.reply_text(
            "\n".join([
                f"❌ *Failed:* `{escape(e['url'])}`",
                f"⚠️ {escape(e['error'])}",
            ]),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    return


# ── Admin: notify on new user ─────────────────────────────────────────────────

async def notify_admins_new_user(context: ContextTypes.DEFAULT_TYPE, user):
    from db import get_admin_ids
    admin_ids = get_admin_ids()
    username = f"@{user.username}" if user.username else "No username"
    text = "\n".join([
        "🔔 *New Access Request*",
        DIVIDER,
        f"👤 Name       →  {escape(user.full_name or 'Unknown')}",
        f"🔖 Username →  {escape(username)}",
        f"🆔 User ID   →  `{user.id}`",
        "",
        f"Use `/approve {user.id}` to grant access\\.",
    ])
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{user.id}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"deny:{user.id}"),
        ]
    ])
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(
                admin_id, text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
            )
        except Exception as e:
            log.warning(f"Could not notify admin {admin_id}: {e}")

# ── Admin commands ────────────────────────────────────────────────────────────

async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return
    pending = get_pending_users()
    if not pending:
        await update.message.reply_text("✅ No pending users\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    lines = [f"⏳ *Pending Users \\({len(pending)}\\):*\n"]
    buttons = []
    for u in pending:
        uname = f"@{u['username']}" if u.get("username") else "No username"
        lines.append(f"👤 {escape(u.get('full_name','Unknown'))} \\| {escape(uname)} \\| `{u['user_id']}`")
        buttons.append([
            InlineKeyboardButton(f"✅ Approve {u['user_id']}", callback_data=f"approve:{u['user_id']}"),
            InlineKeyboardButton(f"❌ Deny {u['user_id']}", callback_data=f"deny:{u['user_id']}"),
        ])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )

async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/approve <user_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    approve_user(target_id)
    info = get_user_info(target_id)
    name = escape(info.get("full_name", "Unknown")) if info else str(target_id)
    await update.message.reply_text(
        f"✅ User {name} \\(`{target_id}`\\) has been *approved*\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    try:
        await context.bot.send_message(
            target_id,
            "🎉 *Your access has been approved\\!*\n\n"
            "You can now generate protected links\\.\n"
            "Just send me a link to get started\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        log.warning(f"Could not notify user {target_id}: {e}")

async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/revoke <user_id>`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    revoke_user(target_id)
    await update.message.reply_text(
        f"🚫 User `{target_id}` access has been *revoked*\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    try:
        await context.bot.send_message(
            target_id,
            "⛔ Your access to this bot has been revoked by an admin.",
        )
    except Exception:
        pass

async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return
    await update.message.reply_text("🔄 *Restarting bot\\.\\.\\.*", parse_mode=ParseMode.MARKDOWN_V2)
    log.info(f"Restart triggered by admin {user.id}")
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ── Startup notification ──────────────────────────────────────────────────────

async def notify_admins_on_startup(app: Application):
    from db import get_admin_ids
    admin_ids = get_admin_ids()
    for admin_id in admin_ids:
        try:
            await app.bot.send_message(
                admin_id,
                "✅ *Bot restarted successfully\\!*",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as e:
            log.warning(f"Could not notify admin {admin_id} on startup: {e}")

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return
    users = get_all_users()
    approved = [u for u in users if u.get("approved")]
    if not approved:
        await update.message.reply_text("No approved users yet\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    lines = [f"👥 *Approved Users \\({len(approved)}\\):*\n"]
    for u in approved:
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(f"• {escape(u.get('full_name','?'))} \\| {escape(uname)} \\| `{u['user_id']}`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)

# ── Inline button callbacks ───────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    # ── "I Joined" button for force subscribe ──
    if query.data == "check_sub":
        if await is_subscribed(context.bot, user.id):
            await query.edit_message_text(
                "✅ *Thanks for joining\\! You can now use the bot\\.*\n\nSend /start to begin\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        else:
            await query.answer(
                "❌ You haven't joined yet! Please join and try again.",
                show_alert=True,
            )
        return

    # ── Screens reachable from /start (Help, About) ──
    if query.data in ("show_help", "show_about"):
        text = {
            "show_help": build_help_text(),
            "show_about": build_about_text(),
        }[query.data]
        home_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="go_home")],
        ])
        await _edit_screen(query, text, home_keyboard)
        return

    # ── Dashboard screen ──
    if query.data == "show_dashboard":
        await _edit_screen(query, build_dashboard_text(), build_dashboard_keyboard())
        return

    # ── Dashboard sub-sections (Statistics, Security, History, Logs, Settings) ──
    if query.data in DASHBOARD_SECTIONS:
        await _edit_screen(
            query,
            build_dashboard_section_text(query.data),
            build_dashboard_section_keyboard(),
        )
        return

    # ── Sites Manager ──
    if query.data == "dash_sites":
        sites = get_sites(user.id)
        await _edit_screen(query, build_sites_text(sites), build_sites_keyboard(sites))
        return

    if query.data == "site_add":
        context.user_data["awaiting_site"] = "domain"
        context.user_data.pop("pending_site_domain", None)
        prompt = "\n".join([
            "📤 *Send me a shortlink URL* \\(e\\.g\\., arolinks\\.com, avbypassbot\\.koyeb\\.app\\)\\.\\.\\.",
            "",
            "_/cancel \\- to cancel this process\\._",
        ])
        await _edit_screen(query, prompt, None)
        return

    if query.data.startswith("site_view:"):
        site_id = int(query.data.split(":")[1])
        site = get_site(site_id, user.id)
        if not site:
            await query.answer("❌ Site not found.", show_alert=True)
            return
        await _edit_screen(query, build_site_detail_text(site), build_site_detail_keyboard(site_id))
        return

    if query.data.startswith("site_devapi:"):
        site_id = int(query.data.split(":")[1])
        site = get_site(site_id, user.id)
        if not site:
            await query.answer("❌ Site not found.", show_alert=True)
            return
        await _edit_screen(query, build_site_devapi_text(site), build_site_devapi_keyboard(site_id))
        return

    if query.data.startswith("site_delete:"):
        site_id = int(query.data.split(":")[1])
        delete_site(site_id, user.id)
        await query.answer("🗑️ Site deleted.")
        sites = get_sites(user.id)
        await _edit_screen(query, build_sites_text(sites), build_sites_keyboard(sites))
        return

    # ── Home button — go back to start message ──
    if query.data == "go_home":
        await _edit_screen(query, build_welcome_text(user, context), build_home_keyboard(user))
        return

    # ── Approve / Deny buttons (admin only) ──
    if not is_admin(user.id):
        await query.answer("🚫 Not authorized.", show_alert=True)
        return

    action, target_str = query.data.split(":", 1)
    target_id = int(target_str)
    info = get_user_info(target_id)
    name = info.get("full_name", str(target_id)) if info else str(target_id)

    if action == "approve":
        approve_user(target_id)
        await query.edit_message_text(
            f"✅ *Approved:* {escape(name)} \\(`{target_id}`\\)",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        try:
            await context.bot.send_message(
                target_id,
                "🎉 *Your access has been approved\\!*\n\n"
                "You can now generate protected links\\.\n"
                "Just send me a link to get started\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            pass
    elif action == "deny":
        revoke_user(target_id)
        await query.edit_message_text(
            f"❌ *Denied:* {escape(name)} \\(`{target_id}`\\)",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        try:
            await context.bot.send_message(
                target_id,
                "⛔ Your access request was denied by an admin.",
            )
        except Exception:
            pass

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(notify_admins_on_startup).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("restart", cmd_restart))

    # Inline buttons
    app.add_handler(CallbackQueryHandler(
        handle_callback,
        pattern=r"^(approve|deny):\d+$|^check_sub$|^show_help$|^show_about$|^show_dashboard$|^go_home$"
                r"|^dash_(sites|stats|security|history|logs|settings)$"
                r"|^site_add$|^site_view:\d+$|^site_delete:\d+$|^site_devapi:\d+$",
    ))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("VMMrx Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
