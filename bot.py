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
        [InlineKeyboardButton("✅ I Joined", callback_data="check_sub")],
    ])
    await update.effective_message.reply_text(
        "⚠️ *You must join our channel to use this bot\\!*\n\n"
        f"👉 Join: {escape(channel)}\n\n"
        "After joining tap *✅ I Joined* below\\.",
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

    welcome = (
        "⚡ *Welcome to VMMrx Protection Bot* ⚡\n\n"
        "I help you generate *Cloudflare\\-protected links* that keep your content safe\\.\n\n"
        "🔐 *Two powerful modes:*\n"
        "  🔗 `/lksfy` — Shorten with *lksfy* \\+ Cloudflare protection\n"
        "  🛡️ `/direct` — *Cloudflare protection only* \\(no shortener\\)\n\n"
        "📦 *Bulk mode supported\\!* — Paste multiple URLs \\(one per line\\)\n\n"
        "📋 *Commands:*\n"
        "  `/start` — Show this message\n"
        "  `/lksfy` — Switch to lksfy\\+protect mode\n"
        "  `/direct` — Switch to direct\\-protect mode\n"
        "  `/mode` — See your current mode\n"
        "  `/help` — Detailed help\n\n"
    )

    if is_admin(user.id):
        welcome += (
            "👑 *Admin Commands:*\n"
            "  `/pending` — View users waiting for approval\n"
            "  `/approve <user\\_id>` — Approve a user\n"
            "  `/revoke <user\\_id>` — Revoke a user's access\n"
            "  `/users` — List all approved users\n\n"
        )

    if is_approved(user.id):
        welcome += "✅ *Your account is approved\\. Start generating links\\!*"
    else:
        welcome += (
            "⏳ *Your account is pending admin approval\\.*\n"
            "You'll be notified once approved\\."
        )
        await notify_admins_new_user(context, user)
        add_pending_user(user.id, user.username or "", user.full_name or "")

    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN_V2)

# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return

    text = (
        "📖 *VMMrx Bot — Help Guide*\n\n"
        "*🔗 Mode 1 — lksfy \\+ Protect* `/lksfy`\n"
        "Links are first shortened via *lksfy* then wrapped with Cloudflare protection\\.\n"
        "You receive: `Original link` \\+ `lksfy link` \\+ `protected link`\n\n"
        "*🛡️ Mode 2 — Direct Protect* `/direct`\n"
        "Links are protected directly via Cloudflare — *no shortener*\\.\n"
        "You receive: `Original link` \\+ `protected link`\n\n"
        "*📦 Bulk Mode*\n"
        "Simply paste multiple URLs \\(one per line\\) after choosing a mode\\.\n"
        "All links will be processed at once\\.\n\n"
        "*📌 How to use:*\n"
        "1\\. Send `/lksfy` or `/direct` to choose mode\n"
        "2\\. Paste one or more URLs\n"
        "3\\. Receive your protected links instantly\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

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
    if current == "lksfy":
        await update.message.reply_text("🔗 Current mode: *lksfy \\+ Protect*\nSend URLs to generate links\\.", parse_mode=ParseMode.MARKDOWN_V2)
    elif current == "direct":
        await update.message.reply_text("🛡️ Current mode: *Direct Protect*\nSend URLs to generate links\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text("⚠️ No mode selected\\. Use `/lksfy` or `/direct` first\\.", parse_mode=ParseMode.MARKDOWN_V2)

# ── /lksfy ────────────────────────────────────────────────────────────────────

async def cmd_lksfy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        await send_force_sub_message(update)
        return
    if not is_approved(user.id):
        await update.message.reply_text("⏳ You're not approved yet. Please wait for admin approval.")
        return
    context.user_data["mode"] = "lksfy"
    await update.message.reply_text(
        "🔗 *lksfy \\+ Protect mode activated\\!*\n\n"
        "Now send me one or more URLs \\(one per line\\) to generate:\n"
        "• Original link\n"
        "• lksfy shortened link\n"
        "• Cloudflare\\-protected link",
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
        "🛡️ *Direct Protect mode activated\\!*\n\n"
        "Now send me one or more URLs \\(one per line\\) to generate:\n"
        "• Original link\n"
        "• Cloudflare\\-protected link",
        parse_mode=ParseMode.MARKDOWN_V2,
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
            "⏳ Your account is *pending admin approval*\\.\n"
            "You'll receive a notification once approved\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        add_pending_user(user.id, user.username or "", user.full_name or "")
        await notify_admins_new_user(context, user)
        return

    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text(
            "⚠️ Please choose a mode first\\!\n\n"
            "• `/lksfy` — lksfy \\+ Cloudflare protect\n"
            "• `/direct` — Cloudflare protect only",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    text = update.message.text or ""
    urls = extract_urls(text)

    if not urls:
        await update.message.reply_text(
            "❌ No valid URLs found\\. Please send URLs starting with `http://` or `https://`\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    is_bulk = len(urls) > 1
    processing_msg = await update.message.reply_text(
        f"⚙️ Processing *{len(urls)} link{'s' if is_bulk else ''}*\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    # ── Generate protected URLs for all links ─────────────────────────────────

    url_map: dict[str, dict] = {}   # original_url -> full API response data
    errors = []

    for i, url in enumerate(urls, 1):
        try:
            if mode == "lksfy":
                data = await generate_lksfy_link(url)
                url_map[url] = data   # has: short_url, protected_url
            else:
                data = await generate_direct_link(url)
                url_map[url] = data   # has: protected_url, original_url
        except Exception as e:
            log.warning(f"Error processing {url}: {e}")
            errors.append({"index": i, "url": url, "error": str(e)})

    await processing_msg.delete()

    # ── Bulk mode: reply with original text, URLs swapped, formatting kept ────

    if is_bulk:
        # Replace each original URL in the raw text with its protected version
        converted_text = text
        for orig_url, data in url_map.items():
            converted_text = converted_text.replace(orig_url, data["protected_url"])

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

        await update.message.reply_text(
            converted_text,
            entities=adjusted_entities if adjusted_entities else None,
        )

        # Report any errors separately
        for e in errors:
            await update.message.reply_text(
                f"❌ *Failed:* `{escape(e['url'])}`\n⚠️ {escape(e['error'])}",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        return

    # ── Single link mode: show original result cards ──────────────────────────

    results = []
    for i, (url, data) in enumerate(url_map.items(), 1):
        if mode == "lksfy":
            results.append({
                "index": i, "url": url,
                "short_url": data["short_url"],
                "protected_url": data["protected_url"],
                "mode": "lksfy",
            })
        else:
            results.append({
                "index": i, "url": url,
                "protected_url": data["protected_url"],
                "original_url": url,
                "mode": "direct",
            })

    def build_result_msg(r: dict, total: int) -> str:
        prefix = f"🔢 *Link {r['index']} of {total}*\n\n" if total > 1 else ""
        if r["mode"] == "lksfy":
            return (
                f"{prefix}"
                f"🌐 *Original Link:*\n`{escape(r['url'])}`\n\n"
                f"🔗 *LKSFY Link:*\n`{escape(r['short_url'])}`\n\n"
                f"🛡️ *Protected Link:*\n`{escape(r['protected_url'])}`"
            )
        else:
            return (
                f"{prefix}"
                f"🌐 *Original Link:*\n`{escape(r['original_url'])}`\n\n"
                f"🛡️ *Protected Link:*\n`{escape(r['protected_url'])}`"
            )

    def build_error_msg(e: dict, total: int) -> str:
        prefix = f"🔢 *Link {e['index']} of {total}*\n\n" if total > 1 else ""
        return (
            f"{prefix}"
            f"❌ *Failed to generate link*\n\n"
            f"🌐 *Your URL:* `{escape(e['url'])}`\n"
            f"⚠️ Error: {escape(e['error'])}"
        )

    total = len(urls)

    for r in results:
        await update.message.reply_text(
            build_result_msg(r, total),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_to_message_id=update.message.message_id,
        )

    for e in errors:
        await update.message.reply_text(
            build_error_msg(e, total),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_to_message_id=update.message.message_id,
        )

# ── Admin: notify on new user ─────────────────────────────────────────────────

async def notify_admins_new_user(context: ContextTypes.DEFAULT_TYPE, user):
    from db import get_admin_ids
    admin_ids = get_admin_ids()
    username = f"@{user.username}" if user.username else "No username"
    text = (
        f"🔔 *New User Requesting Access*\n\n"
        f"👤 Name: {escape(user.full_name or 'Unknown')}\n"
        f"🔖 Username: {escape(username)}\n"
        f"🆔 User ID: `{user.id}`\n\n"
        f"Use `/approve {user.id}` to grant access\\."
    )
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
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("users", cmd_users))

    # Inline buttons
    app.add_handler(CallbackQueryHandler(
        handle_callback,
        pattern=r"^(approve|deny):\d+$|^check_sub$",
    ))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("VMMrx Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
