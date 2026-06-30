"""
Warranty Tracker Telegram Bot — by RxxK
=========================================
Storage: MongoDB (pymongo)
Features: Category system, Edit, Stats, Broadcast, Ban/Block,
          Activity Log, Export, Multi-language (EN/HI),
          Full Inline Keyboard Navigation
"""

import csv
import io
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

import pytz
from pymongo import MongoClient, DESCENDING
from pymongo.collection import Collection
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
ADMIN_ID   = int(os.environ.get("ADMIN_ID", "0"))
MONGODB_URI = os.environ.get("MONGODB_URI", "")

IST = pytz.timezone("Asia/Kolkata")

# /add conversation states
ASK_EMAIL, ASK_DURATION, ASK_CUSTOM_DAYS, ASK_CATEGORY, ASK_TIME = range(5)

# /edit conversation states
EDIT_CHOICE, EDIT_DURATION, EDIT_CUSTOM_DAYS, EDIT_CATEGORY, EDIT_TIME = range(5, 10)

WARRANTY_OPTIONS = {
    "1day":   ("1 Day",   1),
    "15days": ("15 Days", 15),
    "20days": ("20 Days", 20),
}

# awaiting_input values (used by button-triggered text flows)
AWAIT_SEARCH    = "search_email"
AWAIT_CATEGORY  = "category_browse"
AWAIT_BROADCAST = "broadcast_msg"
AWAIT_BAN       = "ban_id"
AWAIT_UNBAN     = "unban_id"
AWAIT_REMOVE    = "remove_email_menu"
AWAIT_EDIT      = "edit_email_menu"

# ---------------------------------------------------------------------------
# MULTI-LANGUAGE MESSAGES
# ---------------------------------------------------------------------------
MESSAGES = {
    "en": {
        "welcome":        "👋 *Welcome to Warranty Tracker*\n\n👥 Members: *{members}*\n📧 Tracked: *{emails}* emails\n\n🔍 Use the buttons below or type `/list <email>` to check warranty status",
        "user_commands":  "\n\n📌 *Commands*\n🔍 /list <email>\n🏷 /category <tag>\n🌐 /language",
        "admin_panel":    "\n\n👑 *Admin Commands*\n➕ /add  ✏️ /edit  🗑 /remove\n📋 /alllist  📊 /stats  📢 /broadcast\n📤 /export  📜 /logs  🚫 /ban  ✅ /unban",
        "search_hint":    "🔍 Please search using: /list <email>",
        "not_found":      "🔍 No record found for *{email}*",
        "added":          "✅ *Warranty Added!*\n\n📧 {email}\n🏷 Category: *{category}*\n📦 {duration_label}\n⏰ Expires: {expiry}",
        "removed":        "🗑 Removed *{email}* successfully",
        "banned":         "⛔ You are banned from using this bot.",
        "no_emails":      "📭 No emails added yet.",
        "updated":        "✅ *{email}* updated successfully",
        "category_empty": "📭 No emails found in category *{category}*",
        "language_set":   "✅ Language set to *English*",
    },
    "hi": {
        "welcome":        "👋 *वारंटी ट्रैकर में स्वागत है*\n\n👥 सदस्य: *{members}*\n📧 ट्रैक किए: *{emails}* ईमेल\n\n🔍 नीचे दिए बटन दबाएं या `/list <email>` टाइप करें",
        "user_commands":  "\n\n📌 *कमांड*\n🔍 /list <email>\n🏷 /category <tag>\n🌐 /language",
        "admin_panel":    "\n\n👑 *एडमिन कमांड*\n➕ /add  ✏️ /edit  🗑 /remove\n📋 /alllist  📊 /stats  📢 /broadcast\n📤 /export  📜 /logs  🚫 /ban  ✅ /unban",
        "search_hint":    "🔍 कृपया इस तरह खोजें: /list <email>",
        "not_found":      "🔍 *{email}* के लिए कोई रिकॉर्ड नहीं मिला",
        "added":          "✅ *वारंटी जोड़ी गई!*\n\n📧 {email}\n🏷 श्रेणी: *{category}*\n📦 {duration_label}\n⏰ समाप्ति: {expiry}",
        "removed":        "🗑 *{email}* सफलतापूर्वक हटाया गया",
        "banned":         "⛔ आपको इस बॉट से बैन किया गया है।",
        "no_emails":      "📭 अभी कोई ईमेल नहीं जोड़ा गया।",
        "updated":        "✅ *{email}* सफलतापूर्वक अपडेट किया गया",
        "category_empty": "📭 श्रेणी *{category}* में कोई ईमेल नहीं मिला",
        "language_set":   "✅ भाषा *हिंदी* में सेट की गई",
    },
}


def msg(key: str, lang: str = "en", **kwargs) -> str:
    text = MESSAGES.get(lang, MESSAGES["en"]).get(key) or MESSAGES["en"].get(key, "")
    return text.format(**kwargs) if kwargs else text


# ---------------------------------------------------------------------------
# KEYBOARD BUILDERS
# ---------------------------------------------------------------------------
def back_button() -> InlineKeyboardMarkup:
    """Single 'Back to Menu' button attached to every completed action."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back to Menu", callback_data="menu_home")]])


def main_menu_keyboard(admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🔍 Search Warranty",  callback_data="menu_search"),
            InlineKeyboardButton("🏷 Browse Category",  callback_data="menu_category"),
        ],
        [
            InlineKeyboardButton("🌐 Change Language",  callback_data="menu_language"),
        ],
    ]
    if admin:
        rows += [
            [
                InlineKeyboardButton("➕ Add Warranty",  callback_data="menu_add"),
                InlineKeyboardButton("✏️ Edit Record",   callback_data="menu_edit"),
            ],
            [
                InlineKeyboardButton("🗑 Remove Email",  callback_data="menu_remove"),
                InlineKeyboardButton("📋 View All",      callback_data="menu_alllist"),
            ],
            [
                InlineKeyboardButton("📊 Statistics",    callback_data="menu_stats"),
                InlineKeyboardButton("📢 Broadcast",     callback_data="menu_broadcast"),
            ],
            [
                InlineKeyboardButton("📤 Export CSV",    callback_data="menu_export"),
                InlineKeyboardButton("📜 Activity Log",  callback_data="menu_logs"),
            ],
            [
                InlineKeyboardButton("🚫 Ban User",      callback_data="menu_ban"),
                InlineKeyboardButton("✅ Unban User",    callback_data="menu_unban"),
            ],
        ]
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# MONGODB SETUP (single global connection)
# ---------------------------------------------------------------------------
if not MONGODB_URI:
    print("⚠️ Set MONGODB_URI in Replit Secrets before running.")

mongo_client = MongoClient(MONGODB_URI) if MONGODB_URI else None
db = mongo_client["warranty_bot"] if mongo_client else None


def users_col() -> Collection:   return db["users"]
def emails_col() -> Collection:  return db["emails"]
def activity_col() -> Collection: return db["activity_log"]


# ---------------------------------------------------------------------------
# USER HELPERS
# ---------------------------------------------------------------------------
def user_exists(user_id: int) -> bool:
    return users_col().find_one({"user_id": user_id}) is not None

def add_user(data: dict):
    users_col().insert_one(data)

def get_total_users() -> int:
    return users_col().count_documents({})

def get_user_lang(user_id: int) -> str:
    doc = users_col().find_one({"user_id": user_id}, {"language": 1})
    return (doc.get("language") or "en") if doc else "en"

def set_user_lang(user_id: int, lang: str):
    users_col().update_one({"user_id": user_id}, {"$set": {"language": lang}})

def is_banned(user_id: int) -> bool:
    doc = users_col().find_one({"user_id": user_id}, {"banned": 1})
    return bool(doc.get("banned", False)) if doc else False

def set_ban(user_id: int, banned: bool):
    users_col().update_one({"user_id": user_id}, {"$set": {"banned": banned}}, upsert=True)

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


# ---------------------------------------------------------------------------
# EMAIL HELPERS
# ---------------------------------------------------------------------------
def get_all_emails() -> list:
    return list(emails_col().find({}))

def get_emails_by_search(query: str) -> list:
    return list(emails_col().find({"email": {"$regex": re.escape(query), "$options": "i"}}))

def get_emails_by_category(category: str) -> list:
    return list(emails_col().find({"category": {"$regex": re.escape(category), "$options": "i"}}))

def add_email(data: dict):
    emails_col().insert_one(data)

def delete_email_by_text(email_text: str) -> int:
    result = emails_col().delete_many(
        {"email": {"$regex": f"^{re.escape(email_text)}$", "$options": "i"}}
    )
    return result.deleted_count

def get_unnotified_expired_emails() -> list:
    return list(emails_col().find({"notified": False, "expiry": {"$lte": now_ist().isoformat()}}))

def mark_email_notified(email_id):
    emails_col().update_one({"_id": email_id}, {"$set": {"notified": True}})


# ---------------------------------------------------------------------------
# ACTIVITY LOG
# ---------------------------------------------------------------------------
def log_action(user_id: int, username: str, action: str, details: str = ""):
    activity_col().insert_one({
        "user_id":   user_id,
        "username":  username or str(user_id),
        "action":    action,
        "details":   details,
        "timestamp": now_ist().isoformat(),
    })


# ---------------------------------------------------------------------------
# TIME HELPERS
# ---------------------------------------------------------------------------
TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)\s*$")


def parse_12h_time(text: str):
    m = TIME_RE.match(text)
    if not m:
        return None
    hour, minute, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        return None
    hour24 = (0 if hour == 12 else hour) if period == "AM" else (12 if hour == 12 else hour + 12)
    return hour24, minute


def now_ist():
    return datetime.now(IST)


def fmt_remaining(expiry_iso: str) -> str:
    expiry = datetime.fromisoformat(expiry_iso)
    if expiry.tzinfo is None:
        expiry = IST.localize(expiry)
    diff = expiry - now_ist()
    if diff.total_seconds() <= 0:
        return "⛔ Expired"
    days = diff.days
    hours, rem = divmod(diff.seconds, 3600)
    minutes = rem // 60
    return f"{days}d {hours}h {minutes}m left"


# ---------------------------------------------------------------------------
# SHARED HELPER — build & send main menu
# ---------------------------------------------------------------------------
async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send (or re-send) the main menu. Works from both messages and callbacks."""
    user = update.effective_user
    lang = get_user_lang(user.id)
    total_members = get_total_users()
    total_emails_count = emails_col().count_documents({})

    text = msg("welcome", lang, members=total_members, emails=total_emails_count)
    text += msg("user_commands", lang)
    if is_admin(user.id):
        text += msg("admin_panel", lang)

    kb = main_menu_keyboard(is_admin(user.id))

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("⛔ You are banned from using this bot.")
        return

    is_new = not user_exists(user.id)
    if is_new:
        add_user({
            "user_id":    user.id,
            "username":   user.username or "",
            "first_name": user.first_name or "",
            "joined":     now_ist().isoformat(),
            "language":   "en",
            "banned":     False,
        })
        if ADMIN_ID:
            try:
                total = get_total_users()
                uname = f"@{user.username}" if user.username else "N/A"
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"🆕 *New User Joined*\n\n"
                        f"👤 {user.first_name} ({uname})\n"
                        f"🆔 `{user.id}`\n"
                        f"👥 Total: *{total}*"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    await send_main_menu(update, context)


# ---------------------------------------------------------------------------
# CORE SEARCH LOGIC (shared by /list command and button flow)
# ---------------------------------------------------------------------------
async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, search_text: str):
    user = update.effective_user
    lang = get_user_lang(user.id)
    matches = get_emails_by_search(search_text)
    log_action(user.id, user.username or "", "search", search_text)

    if not matches:
        await update.message.reply_text(
            msg("not_found", lang, email=search_text),
            parse_mode="Markdown",
            reply_markup=back_button(),
        )
        return

    if len(matches) == 1:
        data = matches[0]
        reply = (
            f"📧 *{data['email']}*\n"
            f"🏷 Category: *{data.get('category', 'General')}*\n"
            f"📦 Warranty: *{data['duration_label']}*\n"
            f"⏳ {fmt_remaining(data['expiry'])}"
        )
    else:
        NUMS = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        reply = f"🔍 Found *{len(matches)}* records for *{matches[0]['email']}*:\n"
        for i, data in enumerate(matches):
            num = NUMS[i] if i < len(NUMS) else f"{i+1}."
            reply += (
                f"\n{num} 🏷 {data.get('category','General')}\n"
                f"   📦 {data['duration_label']} — ⏳ {fmt_remaining(data['expiry'])}"
            )

    await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=back_button())


# ---------------------------------------------------------------------------
# /list — slash command
# ---------------------------------------------------------------------------
async def list_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_lang(user.id)
    if is_banned(user.id):
        await update.message.reply_text(msg("banned", lang))
        return
    search_text = " ".join(context.args).strip() if context.args else ""
    if not search_text:
        await update.message.reply_text(msg("search_hint", lang), reply_markup=back_button())
        return
    await _do_search(update, context, search_text)


# ---------------------------------------------------------------------------
# CORE CATEGORY LOGIC
# ---------------------------------------------------------------------------
async def _do_category(update: Update, context: ContextTypes.DEFAULT_TYPE, tag: str):
    user = update.effective_user
    lang = get_user_lang(user.id)
    matches = get_emails_by_category(tag)
    if not matches:
        await update.message.reply_text(
            msg("category_empty", lang, category=tag),
            parse_mode="Markdown",
            reply_markup=back_button(),
        )
        return
    lines = [f"🏷 *Category: {tag}*\n"]
    for data in matches:
        lines.append(f"📧 {data['email']} — ⏳ {fmt_remaining(data['expiry'])}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=back_button())


# ---------------------------------------------------------------------------
# /category — slash command
# ---------------------------------------------------------------------------
async def category_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_lang(user.id)
    if is_banned(user.id):
        await update.message.reply_text(msg("banned", lang))
        return
    tag = " ".join(context.args).strip() if context.args else ""
    if not tag:
        await update.message.reply_text("🏷 Usage: /category <tag_name>", reply_markup=back_button())
        return
    await _do_category(update, context, tag)


# ---------------------------------------------------------------------------
# /alllist (admin only) — grouped by category
# ---------------------------------------------------------------------------
async def alllist_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can view all emails.")
        return
    all_emails = get_all_emails()
    if not all_emails:
        await update.message.reply_text("📭 No emails added yet.", reply_markup=back_button())
        return
    grouped = defaultdict(list)
    for data in all_emails:
        grouped[data.get("category", "General")].append(data)
    lines = ["📋 *All Tracked Emails*\n"]
    for cat in sorted(grouped.keys()):
        lines.append(f"🏷 *{cat}*")
        for data in grouped[cat]:
            lines.append(f"  📧 {data['email']} — ⏳ {fmt_remaining(data['expiry'])}")
        lines.append("")
    await update.message.reply_text("\n".join(lines).strip(), parse_mode="Markdown", reply_markup=back_button())


# ---------------------------------------------------------------------------
# /add (admin only) — conversation; entry via command OR button
# ---------------------------------------------------------------------------
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer("⛔ Admins only", show_alert=True)
        else:
            await update.message.reply_text("⛔ Only admin can add emails.")
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("📧 Send the email/outlook to add:")
    else:
        await update.message.reply_text("📧 Send the email/outlook to add:")
    return ASK_EMAIL


async def add_email_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email:
        await update.message.reply_text("⛔ That doesn't look like a valid email. Try again:")
        return ASK_EMAIL
    context.user_data["new_email"] = email
    keyboard = [
        [InlineKeyboardButton("1 Day",    callback_data="dur_1day")],
        [InlineKeyboardButton("15 Days",  callback_data="dur_15days")],
        [InlineKeyboardButton("20 Days",  callback_data="dur_20days")],
        [InlineKeyboardButton("✏️ Custom", callback_data="dur_custom")],
    ]
    await update.message.reply_text("📦 Select warranty duration:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_DURATION


async def add_duration_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("dur_", "")
    if key == "custom":
        await query.edit_message_text("✏️ Enter custom number of days (e.g. 7):")
        return ASK_CUSTOM_DAYS
    label, days = WARRANTY_OPTIONS[key]
    context.user_data["duration_label"] = label
    context.user_data["duration_days"]  = days
    await query.edit_message_text(
        f"📦 *Duration:* {label}\n\n"
        "🏷 Enter category/tag (e.g. Client A, Personal)\nor send *skip* for General:",
        parse_mode="Markdown",
    )
    return ASK_CATEGORY


async def add_custom_days_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("⛔ Please enter a valid positive number (e.g. 7):")
        return ASK_CUSTOM_DAYS
    days  = int(text)
    label = f"{days} Days"
    context.user_data["duration_label"] = label
    context.user_data["duration_days"]  = days
    await update.message.reply_text(
        f"📦 *Duration:* {label}\n\n"
        "🏷 Enter category/tag (e.g. Client A, Personal)\nor send *skip* for General:",
        parse_mode="Markdown",
    )
    return ASK_CATEGORY


async def add_category_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["category"] = "General" if text.lower() == "skip" or not text else text
    await update.message.reply_text(
        f"🏷 *Category:* {context.user_data['category']}\n\n"
        "⏰ Now send start time (12-hr IST, e.g. `02:30 PM`):",
        parse_mode="Markdown",
    )
    return ASK_TIME


async def add_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_12h_time(update.message.text)
    if not parsed:
        await update.message.reply_text(
            "⛔ Invalid format. Send time like `02:30 PM` (12-hr IST):",
            parse_mode="Markdown",
        )
        return ASK_TIME
    hour24, minute = parsed
    start_dt  = now_ist().replace(hour=hour24, minute=minute, second=0, microsecond=0)
    days      = context.user_data["duration_days"]
    expiry_dt = start_dt + timedelta(days=days)
    email         = context.user_data["new_email"]
    category      = context.user_data.get("category", "General")
    duration_label = context.user_data["duration_label"]
    add_email({
        "email":          email,
        "category":       category,
        "duration_label": duration_label,
        "duration_days":  days,
        "start":          start_dt.isoformat(),
        "expiry":         expiry_dt.isoformat(),
        "notified":       False,
        "added_by":       update.effective_user.id,
    })
    log_action(update.effective_user.id, update.effective_user.username or "", "add", email)
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(
        msg("added", lang, email=email, category=category, duration_label=duration_label,
            expiry=expiry_dt.strftime("%d-%b-%Y %I:%M %p") + " IST"),
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.", reply_markup=back_button())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /edit (admin only) — conversation; entry via command OR button-then-text
# ---------------------------------------------------------------------------
async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        if update.callback_query:
            await update.callback_query.answer("⛔ Admins only", show_alert=True)
        else:
            await update.message.reply_text("⛔ Only admin can edit records.")
        return ConversationHandler.END

    target = " ".join(context.args).strip() if context.args else ""
    if not target:
        # triggered from button — context.args is empty, so ask for email
        await update.message.reply_text("✏️ Send the email address you want to edit:")
        return ASK_EMAIL  # reuse state; we detect it via user_data flag below

    return await _do_edit_lookup(update, context, target)


async def _do_edit_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    matches = get_emails_by_search(target)
    if not matches:
        await update.message.reply_text("🔍 Email not found.", reply_markup=back_button())
        return ConversationHandler.END
    doc = matches[0]
    context.user_data["edit_id"]    = doc["_id"]
    context.user_data["edit_email"] = doc["email"]
    context.user_data["edit_days"]  = doc.get("duration_days", 1)
    keyboard = [
        [InlineKeyboardButton("📦 Change Duration", callback_data="edit_duration")],
        [InlineKeyboardButton("🏷 Change Category",  callback_data="edit_category")],
        [InlineKeyboardButton("⏰ Change Time",      callback_data="edit_time")],
    ]
    await update.message.reply_text(
        f"✏️ Editing: *{doc['email']}*\n"
        f"🏷 {doc.get('category','General')} — ⏳ {fmt_remaining(doc['expiry'])}\n\n"
        "What do you want to change?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return EDIT_CHOICE


# edit_start is also the handler when user typed email after pressing Edit button
# We distinguish: if edit_id already set we went through lookup, else email was just sent
async def edit_email_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the email text the user sends after pressing ✏️ Edit Record button."""
    target = update.message.text.strip()
    return await _do_edit_lookup(update, context, target)


async def edit_choice_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "edit_duration":
        keyboard = [
            [InlineKeyboardButton("1 Day",    callback_data="editdur_1day")],
            [InlineKeyboardButton("15 Days",  callback_data="editdur_15days")],
            [InlineKeyboardButton("20 Days",  callback_data="editdur_20days")],
            [InlineKeyboardButton("✏️ Custom", callback_data="editdur_custom")],
        ]
        await query.edit_message_text("📦 Select new warranty duration:", reply_markup=InlineKeyboardMarkup(keyboard))
        return EDIT_DURATION
    elif query.data == "edit_category":
        await query.edit_message_text("🏷 Send new category (or *skip* for General):", parse_mode="Markdown")
        return EDIT_CATEGORY
    elif query.data == "edit_time":
        await query.edit_message_text("⏰ Send new start time (12-hr IST, e.g. `02:30 PM`):", parse_mode="Markdown")
        return EDIT_TIME
    return ConversationHandler.END


async def edit_duration_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("editdur_", "")
    if key == "custom":
        await query.edit_message_text("✏️ Enter custom number of days (e.g. 7):")
        return EDIT_CUSTOM_DAYS
    label, days = WARRANTY_OPTIONS[key]
    expiry_dt   = now_ist() + timedelta(days=days)
    emails_col().update_one(
        {"_id": context.user_data["edit_id"]},
        {"$set": {"duration_label": label, "duration_days": days,
                  "expiry": expiry_dt.isoformat(), "notified": False}},
    )
    email = context.user_data["edit_email"]
    log_action(query.from_user.id, query.from_user.username or "", "edit", f"{email} duration→{label}")
    await query.edit_message_text(
        f"✅ *{email}* updated successfully\n📦 Duration: *{label}*\n"
        f"⏰ Expires: {expiry_dt.strftime('%d-%b-%Y %I:%M %p')} IST",
        parse_mode="Markdown",
    )
    await context.bot.send_message(chat_id=query.message.chat_id, text="↩️", reply_markup=back_button())
    context.user_data.clear()
    return ConversationHandler.END


async def edit_custom_days_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("⛔ Please enter a valid positive number (e.g. 7):")
        return EDIT_CUSTOM_DAYS
    days      = int(text)
    label     = f"{days} Days"
    expiry_dt = now_ist() + timedelta(days=days)
    emails_col().update_one(
        {"_id": context.user_data["edit_id"]},
        {"$set": {"duration_label": label, "duration_days": days,
                  "expiry": expiry_dt.isoformat(), "notified": False}},
    )
    email = context.user_data["edit_email"]
    log_action(update.effective_user.id, update.effective_user.username or "", "edit", f"{email} duration→{label}")
    await update.message.reply_text(
        f"✅ *{email}* updated successfully\n📦 Duration: *{label}*\n"
        f"⏰ Expires: {expiry_dt.strftime('%d-%b-%Y %I:%M %p')} IST",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def edit_category_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text    = update.message.text.strip()
    new_cat = "General" if text.lower() == "skip" or not text else text
    emails_col().update_one({"_id": context.user_data["edit_id"]}, {"$set": {"category": new_cat}})
    email = context.user_data["edit_email"]
    log_action(update.effective_user.id, update.effective_user.username or "", "edit", f"{email} category→{new_cat}")
    await update.message.reply_text(
        f"✅ *{email}* updated successfully\n🏷 Category: *{new_cat}*",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def edit_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_12h_time(update.message.text)
    if not parsed:
        await update.message.reply_text("⛔ Invalid format. Send time like `02:30 PM` (12-hr IST):", parse_mode="Markdown")
        return EDIT_TIME
    hour24, minute = parsed
    start_dt  = now_ist().replace(hour=hour24, minute=minute, second=0, microsecond=0)
    days      = context.user_data.get("edit_days", 1)
    expiry_dt = start_dt + timedelta(days=days)
    emails_col().update_one(
        {"_id": context.user_data["edit_id"]},
        {"$set": {"start": start_dt.isoformat(), "expiry": expiry_dt.isoformat(), "notified": False}},
    )
    email = context.user_data["edit_email"]
    log_action(update.effective_user.id, update.effective_user.username or "", "edit",
               f"{email} time→{start_dt.strftime('%I:%M %p')}")
    await update.message.reply_text(
        f"✅ *{email}* updated successfully\n⏰ Expires: {expiry_dt.strftime('%d-%b-%Y %I:%M %p')} IST",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.", reply_markup=back_button())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /remove (admin only)
# ---------------------------------------------------------------------------
async def remove_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can remove emails.")
        return
    all_emails = get_all_emails()
    if not all_emails:
        await update.message.reply_text("📭 No emails to remove.", reply_markup=back_button())
        return
    if not context.args:
        lines = ["*Usage:* /remove <email>\n\n📋 *Current emails:*"]
        for data in all_emails:
            lines.append(f"• {data['email']} ({data.get('category','General')})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=back_button())
        return
    target  = " ".join(context.args).strip()
    deleted = delete_email_by_text(target)
    if not deleted:
        await update.message.reply_text("🔍 Email not found.", reply_markup=back_button())
        return
    log_action(update.effective_user.id, update.effective_user.username or "", "remove", target)
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(msg("removed", lang, email=target), parse_mode="Markdown", reply_markup=back_button())


# ---------------------------------------------------------------------------
# CORE STATS LOGIC
# ---------------------------------------------------------------------------
async def _do_stats(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    total_users    = get_total_users()
    total_emails   = emails_col().count_documents({})
    active         = emails_col().count_documents({"notified": False})
    expired_count  = emails_col().count_documents({"notified": True})
    pipeline       = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}]
    cat_counts     = list(emails_col().aggregate(pipeline))
    cat_lines      = "\n".join(
        f"  {c['_id'] or 'General'}: *{c['count']}*"
        for c in sorted(cat_counts, key=lambda x: x["_id"] or "")
    )
    text = (
        "📊 *Bot Statistics*\n\n"
        f"👥 Total Users: *{total_users}*\n"
        f"📧 Total Emails: *{total_emails}*\n"
        f"✅ Active: *{active}*\n"
        f"⛔ Expired: *{expired_count}*"
    )
    if cat_lines:
        text += f"\n\n🏷 *By Category:*\n{cat_lines}"
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=back_button())


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can view stats.")
        return
    await _do_stats(update.effective_chat.id, context)


# ---------------------------------------------------------------------------
# CORE BROADCAST LOGIC
# ---------------------------------------------------------------------------
async def _do_broadcast(chat_id: int, admin_id: int, admin_username: str,
                         message_text: str, context: ContextTypes.DEFAULT_TYPE):
    all_users = list(users_col().find({}, {"user_id": 1}))
    success, failed = 0, 0
    for user_doc in all_users:
        try:
            await context.bot.send_message(chat_id=user_doc["user_id"], text=message_text)
            success += 1
        except Exception:
            failed += 1
    log_action(admin_id, admin_username, "broadcast", f"{success} sent")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📢 Broadcast sent to *{success}* users\n(*{failed}* failed)",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can broadcast.")
        return
    if not context.args:
        await update.message.reply_text("📢 Usage: /broadcast <message>", reply_markup=back_button())
        return
    message_text = " ".join(context.args)
    user = update.effective_user
    await _do_broadcast(update.effective_chat.id, user.id, user.username or "", message_text, context)


# ---------------------------------------------------------------------------
# CORE EXPORT LOGIC
# ---------------------------------------------------------------------------
async def _do_export(chat_id: int, admin_id: int, admin_username: str,
                      context: ContextTypes.DEFAULT_TYPE):
    all_emails = get_all_emails()
    if not all_emails:
        await context.bot.send_message(chat_id=chat_id, text="📭 No emails to export.", reply_markup=back_button())
        return
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["email","category","duration_label","start","expiry","status"])
    writer.writeheader()
    for data in all_emails:
        writer.writerow({
            "email":          data.get("email",""),
            "category":       data.get("category","General"),
            "duration_label": data.get("duration_label",""),
            "start":          data.get("start",""),
            "expiry":         data.get("expiry",""),
            "status":         "Expired" if data.get("notified") else "Active",
        })
    output.seek(0)
    file_bytes = output.getvalue().encode("utf-8")
    filename   = f"warranty_export_{now_ist().strftime('%Y%m%d_%H%M')}.csv"
    await context.bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(file_bytes),
        filename=filename,
        caption=f"📤 *Warranty Data Export*\n{len(all_emails)} records",
        parse_mode="Markdown",
    )
    await context.bot.send_message(chat_id=chat_id, text="↩️", reply_markup=back_button())
    log_action(admin_id, admin_username, "export", f"{len(all_emails)} records")


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can export data.")
        return
    user = update.effective_user
    await _do_export(update.effective_chat.id, user.id, user.username or "", context)


# ---------------------------------------------------------------------------
# CORE LOGS LOGIC
# ---------------------------------------------------------------------------
async def _do_logs(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    entries = list(activity_col().find({}).sort("timestamp", DESCENDING).limit(20))
    if not entries:
        await context.bot.send_message(chat_id=chat_id, text="📜 No activity logs yet.", reply_markup=back_button())
        return
    ACTION_EMOJI = {"search":"🔍","add":"➕","remove":"🗑","edit":"✏️","broadcast":"📢","export":"📤"}
    lines = ["📜 *Recent Activity*\n"]
    for e in entries:
        emoji    = ACTION_EMOJI.get(e["action"], "•")
        ts       = e["timestamp"][:16].replace("T", " ")
        user_str = f"@{e['username']}" if e.get("username") else f"id:{e['user_id']}"
        lines.append(f"{emoji} {user_str} — `{e.get('details', e['action'])}` — {ts}")
    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown", reply_markup=back_button())


async def activity_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can view logs.")
        return
    await _do_logs(update.effective_chat.id, context)


# ---------------------------------------------------------------------------
# /ban and /unban (admin only)
# ---------------------------------------------------------------------------
async def _do_ban(chat_id: int, uid: int, banned: bool, context: ContextTypes.DEFAULT_TYPE):
    set_ban(uid, banned)
    action = "banned" if banned else "unbanned"
    emoji  = "🚫" if banned else "✅"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{emoji} User `{uid}` has been *{action}*.",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can ban users.")
        return
    if not context.args:
        await update.message.reply_text("🚫 Usage: /ban <user_id>", reply_markup=back_button())
        return
    try:
        uid = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("⛔ Invalid user ID.", reply_markup=back_button())
        return
    await _do_ban(update.effective_chat.id, uid, True, context)


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only admin can unban users.")
        return
    if not context.args:
        await update.message.reply_text("✅ Usage: /unban <user_id>", reply_markup=back_button())
        return
    try:
        uid = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("⛔ Invalid user ID.", reply_markup=back_button())
        return
    await _do_ban(update.effective_chat.id, uid, False, context)


# ---------------------------------------------------------------------------
# /language
# ---------------------------------------------------------------------------
async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_banned(update.effective_user.id):
        await update.message.reply_text("⛔ You are banned from using this bot.")
        return
    keyboard = [[
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        InlineKeyboardButton("🇮🇳 हिंदी",   callback_data="lang_hi"),
    ]]
    await update.message.reply_text("🌐 Select your language:", reply_markup=InlineKeyboardMarkup(keyboard))


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data.replace("lang_", "")
    set_user_lang(query.from_user.id, lang)
    await query.edit_message_text(msg("language_set", lang), parse_mode="Markdown")
    await context.bot.send_message(chat_id=query.message.chat_id, text="↩️", reply_markup=back_button())


# ---------------------------------------------------------------------------
# MENU BUTTON CALLBACKS  (pattern: ^menu_)
# ---------------------------------------------------------------------------
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    action = query.data         # e.g. "menu_search"
    user   = query.from_user
    lang   = get_user_lang(user.id)

    if is_banned(user.id):
        await query.answer(msg("banned", lang), show_alert=True)
        return

    await query.answer()

    # ── home ──────────────────────────────────────────────────────────────
    if action == "menu_home":
        await send_main_menu(update, context)
        return

    # ── language ──────────────────────────────────────────────────────────
    if action == "menu_language":
        keyboard = [[
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇮🇳 हिंदी",   callback_data="lang_hi"),
        ]]
        await query.message.reply_text("🌐 Select your language:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # ── user actions that need a text response ────────────────────────────
    if action == "menu_search":
        context.user_data["awaiting_input"] = AWAIT_SEARCH
        await query.message.reply_text("📧 Type the email to search:")
        return

    if action == "menu_category":
        context.user_data["awaiting_input"] = AWAIT_CATEGORY
        await query.message.reply_text("🏷 Type the category name:")
        return

    # ── admin-only actions ────────────────────────────────────────────────
    if not is_admin(user.id):
        await query.answer("⛔ Admins only", show_alert=True)
        return

    if action == "menu_alllist":
        all_emails = get_all_emails()
        if not all_emails:
            await query.message.reply_text("📭 No emails added yet.", reply_markup=back_button())
            return
        grouped = defaultdict(list)
        for data in all_emails:
            grouped[data.get("category","General")].append(data)
        lines = ["📋 *All Tracked Emails*\n"]
        for cat in sorted(grouped.keys()):
            lines.append(f"🏷 *{cat}*")
            for data in grouped[cat]:
                lines.append(f"  📧 {data['email']} — ⏳ {fmt_remaining(data['expiry'])}")
            lines.append("")
        await query.message.reply_text("\n".join(lines).strip(), parse_mode="Markdown", reply_markup=back_button())
        return

    if action == "menu_stats":
        await _do_stats(query.message.chat_id, context)
        return

    if action == "menu_export":
        await _do_export(query.message.chat_id, user.id, user.username or "", context)
        return

    if action == "menu_logs":
        await _do_logs(query.message.chat_id, context)
        return

    if action == "menu_broadcast":
        context.user_data["awaiting_input"] = AWAIT_BROADCAST
        await query.message.reply_text("📢 Type the broadcast message:")
        return

    if action == "menu_ban":
        context.user_data["awaiting_input"] = AWAIT_BAN
        await query.message.reply_text("🚫 Send the user_id to ban:")
        return

    if action == "menu_unban":
        context.user_data["awaiting_input"] = AWAIT_UNBAN
        await query.message.reply_text("✅ Send the user_id to unban:")
        return

    if action == "menu_remove":
        context.user_data["awaiting_input"] = AWAIT_REMOVE
        await query.message.reply_text("🗑 Send the email to remove:")
        return

    if action == "menu_edit":
        context.user_data["awaiting_input"] = AWAIT_EDIT
        await query.message.reply_text("✏️ Send the email address to edit:")
        return

    # menu_add is handled by the edit_conv entry point (CallbackQueryHandler)
    # so it won't reach here unless misconfigured


# ---------------------------------------------------------------------------
# GENERAL TEXT HANDLER — for button-triggered awaiting_input flows
# ---------------------------------------------------------------------------
async def awaiting_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting_input")
    if not awaiting:
        return  # nothing pending — ignore (let other handlers take it)

    text = update.message.text.strip()
    user = update.effective_user
    lang = get_user_lang(user.id)
    context.user_data.pop("awaiting_input")     # clear before acting

    if awaiting == AWAIT_SEARCH:
        await _do_search(update, context, text)

    elif awaiting == AWAIT_CATEGORY:
        await _do_category(update, context, text)

    elif awaiting == AWAIT_BROADCAST:
        if not is_admin(user.id):
            await update.message.reply_text("⛔ Only admin can broadcast.")
            return
        await _do_broadcast(update.effective_chat.id, user.id, user.username or "", text, context)

    elif awaiting == AWAIT_BAN:
        if not is_admin(user.id):
            await update.message.reply_text("⛔ Only admin can ban users.")
            return
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("⛔ Invalid user ID.", reply_markup=back_button())
            return
        await _do_ban(update.effective_chat.id, uid, True, context)

    elif awaiting == AWAIT_UNBAN:
        if not is_admin(user.id):
            await update.message.reply_text("⛔ Only admin can unban users.")
            return
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("⛔ Invalid user ID.", reply_markup=back_button())
            return
        await _do_ban(update.effective_chat.id, uid, False, context)

    elif awaiting == AWAIT_REMOVE:
        if not is_admin(user.id):
            await update.message.reply_text("⛔ Only admin can remove emails.")
            return
        deleted = delete_email_by_text(text)
        if not deleted:
            await update.message.reply_text("🔍 Email not found.", reply_markup=back_button())
            return
        log_action(user.id, user.username or "", "remove", text)
        await update.message.reply_text(msg("removed", lang, email=text), parse_mode="Markdown", reply_markup=back_button())

    elif awaiting == AWAIT_EDIT:
        if not is_admin(user.id):
            await update.message.reply_text("⛔ Only admin can edit records.")
            return
        # Fake context.args so _do_edit_lookup works uniformly
        await _do_edit_lookup(update, context, text)
        # After this the user is in EDIT_CHOICE state of edit_conv — handled there


# ---------------------------------------------------------------------------
# Background job — check expiries every 60s
# ---------------------------------------------------------------------------
async def check_expiries(context: ContextTypes.DEFAULT_TYPE):
    for data in get_unnotified_expired_emails():
        mark_email_notified(data["_id"])
        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"⛔ *Warranty Expired!*\n\n"
                        f"📧 {data['email']}\n"
                        f"🏷 {data.get('category','General')}\n"
                        f"📦 Was: {data['duration_label']}"
                    ),
                    parse_mode="Markdown",
                    reply_markup=back_button(),
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if BOT_TOKEN == "PUT_YOUR_TOKEN_HERE" or not ADMIN_ID:
        print("⚠️  Set BOT_TOKEN and ADMIN_ID in Replit Secrets before running.")
    if not MONGODB_URI:
        print("⚠️ Set MONGODB_URI in Replit Secrets before running.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Conversation: /add  (also triggered by menu_add button) ───────────
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(add_start, pattern="^menu_add$"),
        ],
        states={
            ASK_EMAIL:       [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email_received)],
            ASK_DURATION:    [CallbackQueryHandler(add_duration_received, pattern="^dur_")],
            ASK_CUSTOM_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_custom_days_received)],
            ASK_CATEGORY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category_received)],
            ASK_TIME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, add_time_received)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    # ── Conversation: /edit ───────────────────────────────────────────────
    # Note: menu_edit button sets awaiting_input=AWAIT_EDIT, text handler calls
    # _do_edit_lookup which puts user into EDIT_CHOICE state of this conversation.
    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_start)],
        states={
            ASK_EMAIL:        [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_email_input_received)],
            EDIT_CHOICE:      [CallbackQueryHandler(edit_choice_received, pattern="^edit_")],
            EDIT_DURATION:    [CallbackQueryHandler(edit_duration_received, pattern="^editdur_")],
            EDIT_CUSTOM_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_custom_days_received)],
            EDIT_CATEGORY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_category_received)],
            EDIT_TIME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_time_received)],
        },
        fallbacks=[CommandHandler("cancel", edit_cancel)],
    )

    # ── Register handlers ─────────────────────────────────────────────────
    # Conversations first (they capture messages when in their states)
    app.add_handler(add_conv)
    app.add_handler(edit_conv)

    # Slash commands
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("list",      list_emails))
    app.add_handler(CommandHandler("alllist",   alllist_emails))
    app.add_handler(CommandHandler("category",  category_search))
    app.add_handler(CommandHandler("remove",    remove_email))
    app.add_handler(CommandHandler("stats",     stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("ban",       ban_user))
    app.add_handler(CommandHandler("unban",     unban_user))
    app.add_handler(CommandHandler("logs",      activity_logs))
    app.add_handler(CommandHandler("export",    export_csv))
    app.add_handler(CommandHandler("language",  language_cmd))

    # Callback query handlers (buttons)
    app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(menu_callback,     pattern="^menu_"))

    # General text handler for button-triggered input flows (lowest priority)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, awaiting_input_handler))

    app.job_queue.run_repeating(check_expiries, interval=60, first=10)

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
