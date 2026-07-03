"""
VMMrx Protection Bot — Telegram bot for generating protected links.
Supports lksfy mode, direct (Cloudflare-only) mode, bulk generation,
admin-based user authorization, and force subscribe.
"""

import os
import logging
import asyncio
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
    set_shortener_url,
    set_shortener_api,
    get_shortener,
    clear_shortener,
)
from generator import generate_lksfy_link, generate_direct_link

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
FORCE_SUB_CHANNEL = os.environ.get("FORCE_SUB_CHANNEL", "")  # e.g. @yourchannel

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

# ── UI constants ──────────────────────────────────────────────────────────────
DIVIDER = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

def status_badge(ok: bool) -> str:
    return "✅ Active" if ok else "⚪ Inactive"

# ── Shared screen builders (keep /start, /help, and their button versions
#    perfectly in sync so the UI never drifts between screens) ────────────────

def build_welcome_text(user, context: ContextTypes.DEFAULT_TYPE) -> str:
    first_name = escape(user.first_name or "there")
    mode = context.user_data.get("mode")
    backend = context.user_data.get("backend", "worker")
    mode_label = {"lksfy": "🔗 lksfy \\+ Protect", "direct": "🛡️ Direct Protect"}.get(mode, "⚪ Not selected")
    backend_label = "⚡ Cloudflare Worker" if backend == "worker" else "🌐 Vercel"

    lines = [
        f"👋 *Welcome back, {first_name}*",
        "🛡️ *VMMrx Protection Bot*",
        DIVIDER,
        "Generate Cloudflare\\-protected, unbypassable links in seconds\\.",
        "",
        "*✨ What I can do:*",
        "  🔗  Shorten \\+ protect \\(lksfy mode\\)",
        "  🛡️  Protect only \\(direct mode\\)",
        "  📦  Bulk\\-process multiple links at once",
        "  ⚙️  Use *your own* shortener account",
        "",
        "*📊 Your Status:*",
        f"  Mode        →  {mode_label}",
        f"  Backend  →  {backend_label}",
    ]

    if is_admin(user.id):
        lines += [
            "",
            "*👑 Admin Panel:*",
            "  `/pending`        View users awaiting approval",
            "  `/approve id`  Approve a user",
            "  `/revoke id`    Revoke a user's access",
            "  `/users`          List all approved users",
        ]

    lines.append(DIVIDER)
    if is_approved(user.id):
        lines.append("✅ *Account approved — you're all set\\!*")
    else:
        lines.append("⏳ *Awaiting admin approval\\.* You'll be notified the moment you're approved\\.")

    return "\n".join(lines)

def build_home_keyboard(user) -> InlineKeyboardMarkup:
    if is_approved(user.id):
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔗 lksfy Mode", callback_data="set_mode:lksfy"),
                InlineKeyboardButton("🛡️ Direct Mode", callback_data="set_mode:direct"),
            ],
            [InlineKeyboardButton("⚙️ Setup Shortener", callback_data="shortner_open")],
            [InlineKeyboardButton("📖 Help & Guide", callback_data="show_help")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help & Guide", callback_data="show_help")],
    ])

def build_help_text() -> str:
    return "\n".join([
        "📖 *Help & Guide*",
        DIVIDER,
        "*🔐 Modes*",
        "  🔗 `/lksfy`   Shorten \\+ Cloudflare\\-protect",
        "  🛡️ `/direct`  Cloudflare protection only",
        "",
        "*🔗 lksfy \\+ Protect*",
        "Your link is shortened first, then wrapped in Cloudflare protection\\.",
        "You get: `Original` → `Short link` → `Protected link`",
        "",
        "*🛡️ Direct Protect*",
        "Skips the shortener — protects the original link directly\\.",
        "You get: `Original` → `Protected link`",
        "",
        "*📦 Bulk Mode*",
        "Paste multiple URLs \\(one per line\\) after choosing a mode — all are processed together\\.",
        "",
        "*⚙️ Custom Shortener*",
        "Run `/shortner` to connect your *own* shortener account for `/lksfy` mode instead of the bot's default\\.",
        "",
        DIVIDER,
        "*📌 Quick Start*",
        "1️⃣ Choose a mode — `/lksfy` or `/direct`",
        "2️⃣ Paste one or more links",
        "3️⃣ Get your protected link\\(s\\) instantly ⚡",
    ])

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

    await update.message.reply_text(
        build_welcome_text(user, context),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=build_home_keyboard(user),
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

# ── /mode ─────────────────────────────────────────────────────────────────────

async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet.")
        return
    current = context.user_data.get("mode", None)
    backend = context.user_data.get("backend", "worker")
    b_label = "⚡ Cloudflare Worker" if backend == "worker" else "🌐 Vercel"
    mode_label = {"lksfy": "🔗 lksfy \\+ Protect", "direct": "🛡️ Direct Protect"}.get(current, "⚪ Not selected")

    lines = [
        "📊 *Current Session*",
        DIVIDER,
        f"Mode       →  {mode_label}",
        f"Backend →  {b_label}",
    ]
    if not current:
        lines += ["", "Use `/lksfy` or `/direct` to choose a mode\\."]
    else:
        lines += ["", "Send URLs to generate links\\."]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)

# ── /lksfy ────────────────────────────────────────────────────────────────────

async def cmd_lksfy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return

    cfg = get_shortener(user.id)
    if not cfg["url"] or not cfg["api"]:
        text, parse_mode, keyboard = shortner_intro_payload(user.id)
        await update.message.reply_text(
            "⚠️ *You haven't set up a shortener yet\\.*\n"
            "`/lksfy` mode needs your own shortener account\\.\n" + DIVIDER,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=keyboard)
        return

    context.user_data["mode"] = "lksfy"
    await update.message.reply_text(
        "\n".join([
            "🔗 *lksfy \\+ Protect — Activated*",
            DIVIDER,
            "Send one or more URLs \\(one per line\\)\\. For each, you'll get:",
            "  •  Original link",
            "  •  Your shortener's link",
            "  •  Cloudflare\\-protected link",
        ]),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

# ── /direct ───────────────────────────────────────────────────────────────────

async def cmd_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return
    context.user_data["mode"] = "direct"
    await update.message.reply_text(
        "\n".join([
            "🛡️ *Direct Protect — Activated*",
            DIVIDER,
            "Send one or more URLs \\(one per line\\)\\. For each, you'll get:",
            "  •  Original link",
            "  •  Cloudflare\\-protected link",
        ]),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

# ── /worker ───────────────────────────────────────────────────────────────────

async def cmd_worker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return
    context.user_data["backend"] = "worker"
    await update.message.reply_text(
        "\n".join([
            "⚡ *Cloudflare Worker Backend — Selected*",
            DIVIDER,
            "Now choose a mode:",
            "  •  `/lksfy`   shorten \\+ protect",
            "  •  `/direct`  protect only",
        ]),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

# ── /vercel ───────────────────────────────────────────────────────────────────

async def cmd_vercel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return
    context.user_data["backend"] = "vercel"
    await update.message.reply_text(
        "\n".join([
            "🌐 *Vercel Backend — Selected*",
            DIVIDER,
            "Now choose a mode:",
            "  •  `/lksfy`   shorten \\+ protect",
            "  •  `/direct`  protect only",
        ]),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

# ── /shortner ─────────────────────────────────────────────────────────────────

async def cmd_shortner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return
    text, parse_mode, keyboard = shortner_intro_payload(user.id)
    await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=keyboard)

def shortner_intro_payload(user_id: int):
    """Returns (text, parse_mode, reply_markup) for the /shortner intro screen."""
    cfg = get_shortener(user_id)
    url_display = escape(cfg["url"]) if cfg["url"] else "Not set"
    url_status = f"✅ `{url_display}`" if cfg["url"] else "⚪ Not set"
    api_status = "✅ Set" if cfg["api"] else "⚪ Not set"

    text = "\n".join([
        "⚙️ *Manual Shortener Setup*",
        DIVIDER,
        "Connect your *own* shortener \\(GPLinks, ShrinkMe, lksfy, etc\\.\\) "
        "so `/lksfy` mode uses *your* account instead of the bot's default\\.",
        "",
        "*📌 Setup Steps*",
        "1️⃣  Sign up on a shortener with a standard API",
        "     \\(`/api?api=KEY&url=URL&format=json`\\)",
        "2️⃣  Copy your *site domain*, e\\.g\\. `https://gplinks.in`",
        "3️⃣  Copy your *API key* — usually under *Tools → API*",
        "4️⃣  Tap 🌐 *Shortener URL* and send your domain",
        "5️⃣  Tap 🔑 *Shortener API* and send your key",
        "",
        DIVIDER,
        "*📊 Current Settings*",
        f"🌐 URL       →  {url_status}",
        f"🔑 API Key →  {api_status}",
    ])
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Shortener URL", callback_data="shortner_set:url"),
            InlineKeyboardButton("🔑 Shortener API", callback_data="shortner_set:api"),
        ],
        [InlineKeyboardButton("🗑️ Clear Settings", callback_data="shortner_clear")],
        [InlineKeyboardButton("🏠 Home", callback_data="go_home")],
    ])
    return (text, ParseMode.MARKDOWN_V2, keyboard)

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

    # ── Waiting for a /shortner value (URL or API key)? Handle that first. ──
    awaiting = context.user_data.get("awaiting_shortner")
    if awaiting:
        value = (update.message.text or "").strip()
        context.user_data.pop("awaiting_shortner", None)

        if awaiting == "url":
            if not (value.startswith("http://") or value.startswith("https://")):
                await update.message.reply_text(
                    "\n".join([
                        "❌ *Invalid URL*",
                        DIVIDER,
                        "It must start with `http://` or `https://`\\.",
                        "Send /shortner to try again\\.",
                    ]),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return
            set_shortener_url(user.id, value.rstrip("/"))
            await update.message.reply_text("✅ *Shortener URL saved\\!*", parse_mode=ParseMode.MARKDOWN_V2)
        elif awaiting == "api":
            set_shortener_api(user.id, value)
            await update.message.reply_text("✅ *Shortener API key saved\\!*", parse_mode=ParseMode.MARKDOWN_V2)

        text, parse_mode, keyboard = shortner_intro_payload(user.id)
        await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=keyboard)
        return

    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text(
            "\n".join([
                "⚠️ *No Mode Selected*",
                DIVIDER,
                "  •  `/lksfy`   lksfy \\+ Cloudflare protect",
                "  •  `/direct`  Cloudflare protect only",
            ]),
            parse_mode=ParseMode.MARKDOWN_V2,
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

    # ── Generate protected URLs for all links ─────────────────────────────────

    url_map: dict[str, dict] = {}   # original_url -> full API response data
    errors = []

    backend = context.user_data.get("backend", "worker")
    shortener_cfg = get_shortener(user.id) if mode == "lksfy" else {"url": "", "api": ""}

    for i, url in enumerate(urls, 1):
        try:
            if mode == "lksfy":
                data = await generate_lksfy_link(
                    url, backend=backend,
                    shortener_url=shortener_cfg["url"],
                    shortener_api=shortener_cfg["api"],
                )
                url_map[url] = data   # has: short_url, protected_url
            else:
                data = await generate_direct_link(url, backend=backend)
                url_map[url] = data   # has: protected_url, original_url
        except Exception as e:
            log.warning(f"Error processing {url}: {e}")
            errors.append({"index": i, "url": url, "error": str(e)})

    await processing_msg.delete()

    # ── All messages: reply with original text, URLs swapped, formatting kept ──
    # (applies to both single and bulk — text + formatting is always preserved)

    # Replace each original URL in the raw text with its short protected version
    converted_text = text
    for orig_url, data in url_map.items():
        new_url = data.get("short_protected_url") or data["protected_url"]
        converted_text = converted_text.replace(orig_url, new_url)

    # Re-apply Telegram entities (bold, italic, etc.) from the original message,
    # adjusting offsets to account for URL length changes.
    entities = update.message.entities or []
    from telegram import MessageEntity

    # Build adjusted entities: shift offsets for any entity that comes after
    # a replaced URL (since URL lengths may differ).
    # Map of (original offset in original text) -> delta at that point
    # We process replacements in order of appearance.
    # Simpler approach: rebuild entity list based on new text positions.
    adjusted_entities = []

    # For each entity, find its text in the original, locate it in the new text.
    # Since only URLs changed, non-URL entities' surrounding text is unchanged.
    for ent in entities:
        # Extract the entity text from the original (UTF-16 offsets)
        ent_text_orig = text.encode("utf-16-le")[ent.offset*2:(ent.offset+ent.length)*2].decode("utf-16-le")

        # Skip URL entities — those are the replaced links; we don't re-attach them
        if ent.type == MessageEntity.URL:
            continue

        # Find this entity text in the converted text at roughly the same position
        # (non-URL text didn't change, so a simple search from near the same offset works)
        search_start = max(0, ent.offset - 20)
        new_text_segment = converted_text[search_start:]
        pos = new_text_segment.find(ent_text_orig)
        if pos == -1:
            # Fallback: search full text
            pos_full = converted_text.find(ent_text_orig)
            if pos_full == -1:
                continue
            new_offset = pos_full
        else:
            new_offset = search_start + pos

        adjusted_entities.append(
            MessageEntity(
                type=ent.type,
                offset=new_offset,
                length=ent.length,
                url=ent.url if hasattr(ent, "url") else None,
                user=ent.user if hasattr(ent, "user") else None,
                language=ent.language if hasattr(ent, "language") else None,
                custom_emoji_id=ent.custom_emoji_id if hasattr(ent, "custom_emoji_id") else None,
            )
        )

    if url_map:
        await update.message.reply_text(
            f"✅ *{len(url_map)} link{'s' if len(url_map) != 1 else ''} protected\\!*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        await update.message.reply_text(
            converted_text,
            entities=adjusted_entities if adjusted_entities else None,
        )

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
            "Use `/lksfy` or `/direct` to get started\\.",
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

    # ── Help button ──
    if query.data == "show_help":
        home_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="go_home")],
        ])
        await query.edit_message_text(
            build_help_text(),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=home_keyboard,
        )
        return

    # ── Home button — go back to start message ──
    if query.data == "go_home":
        await query.edit_message_text(
            build_welcome_text(user, context),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=build_home_keyboard(user),
        )
        return

    # ── Open shortener setup from /start ──
    if query.data == "shortner_open":
        if not is_approved(user.id):
            await query.answer("⏳ Your account is not approved yet.", show_alert=True)
            return
        text, parse_mode, keyboard = shortner_intro_payload(user.id)
        await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=keyboard)
        return

    # ── Shortener setup buttons ──
    if query.data in ("shortner_set:url", "shortner_set:api"):
        if not is_approved(user.id):
            await query.answer("⏳ Your account is not approved yet.", show_alert=True)
            return
        field = query.data.split(":")[1]
        context.user_data["awaiting_shortner"] = field
        if field == "url":
            prompt = "\n".join([
                "🌐 *Set Shortener URL*",
                DIVIDER,
                "Send your shortener's site domain now\\.",
                "Example: `https://gplinks.in`",
            ])
        else:
            prompt = "\n".join([
                "🔑 *Set Shortener API Key*",
                DIVIDER,
                "Send your API key now\\.",
                "Find it in your shortener dashboard — usually under *Tools → API*\\.",
            ])
        back_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back", callback_data="shortner_open")],
        ])
        await query.edit_message_text(prompt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_keyboard)
        return

    if query.data == "shortner_clear":
        if not is_approved(user.id):
            await query.answer("⏳ Your account is not approved yet.", show_alert=True)
            return
        clear_shortener(user.id)
        text, parse_mode, keyboard = shortner_intro_payload(user.id)
        await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=keyboard)
        return

    # ── Mode buttons from start message ──
    if query.data.startswith("set_mode:"):
        if not is_approved(user.id):
            await query.answer("⏳ Your account is not approved yet.", show_alert=True)
            return
        mode = query.data.split(":")[1]
        context.user_data["mode"] = mode
        label = "🔗 lksfy \\+ Protect" if mode == "lksfy" else "🛡️ Direct Protect"
        await query.answer(f"{'lksfy' if mode == 'lksfy' else 'Direct'} mode set!")
        mode_text = "\n".join([
            f"{label} — *Activated*",
            DIVIDER,
            "Paste your URL\\(s\\) below 👇",
        ])
        mode_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="go_home")],
        ])
        await query.edit_message_text(
            mode_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=mode_keyboard,
        )
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
                "Use `/lksfy` or `/direct` to get started\\.",
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
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("lksfy", cmd_lksfy))
    app.add_handler(CommandHandler("direct", cmd_direct))
    app.add_handler(CommandHandler("worker", cmd_worker))
    app.add_handler(CommandHandler("vercel", cmd_vercel))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("shortner", cmd_shortner))

    # Inline buttons
    app.add_handler(CallbackQueryHandler(
        handle_callback,
        pattern=r"^(approve|deny):\d+$|^check_sub$|^show_help$|^set_mode:(lksfy|direct)$|^go_home$"
                r"|^shortner_set:(url|api)$|^shortner_clear$|^shortner_open$",
    ))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("VMMrx Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
