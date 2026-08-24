"""
DTZ TRIO Matchmaking Bot
------------------------
A Telegram bot for DTZ TRIO members: access-code gated (tied to your WhatsApp
group), text-only profiles, browse-and-like matching, and admin moderation
(ban / report handling).

Setup:
    1. pip install -r requirements.txt
    2. Create a bot with @BotFather on Telegram, get the token
    3. Set environment variables (see README.md)
    4. python bot.py

Author: built for DTZ TRIO
"""

import logging
import os
import random
import sqlite3
import string
from datetime import datetime, date, timedelta, time as dt_time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()
}
DB_PATH = os.environ.get("DB_PATH", "dtztrio.db")

ICEBREAKERS = [
    "One thing that instantly draws you to someone?",
    "Describe your ideal weekend in a sentence.",
    "What's a fun fact about you?",
]

LOOKING_FOR_OPTIONS = ["Friendship", "Something casual", "Something serious", "Not sure yet"]

FRIENDSHIP_QUESTION_SETS = [
    [
        "What's a small thing that instantly makes your day better?",
        "What's something you're weirdly good at?",
        "If you could master any skill overnight, what would it be?",
    ],
    [
        "What's your go-to comfort food?",
        "What's a course or topic you'd love to nerd out about with someone?",
        "What's one thing on your bucket list before you graduate?",
    ],
    [
        "Who's someone who's influenced you a lot, and how?",
        "What's a habit you're proud of building?",
        "What does a perfect Saturday look like for you?",
    ],
    [
        "What's a belief you've changed your mind about recently?",
        "What's your favorite way to unwind after exams?",
        "What's a random fact you love telling people?",
    ],
]

# Smash or Pass: generic, playful personality-trait prompts — never real
# member photos or identities, so nobody is rated without their knowledge.
SMASH_PASS_PROMPTS = [
    "A study partner who always finishes group assignments early",
    "Someone who sends 'good morning' texts every single day",
    "A person who's way too passionate about jollof rice debates",
    "Someone who has the class notes ready before the exam, every time",
    "A person who mentions their CGPA in almost every conversation",
    "Someone who's always 30 minutes late but brings suya to make up for it",
    "A person who quotes movie lines mid-conversation",
    "Someone who insists on splitting every bill to the exact naira",
    "A person who's weirdly, intensely competitive at board games",
    "Someone who replies to a paragraph with just 'k'",
    "A person who remembers everyone's birthday without being told",
    "Someone who always has a wild conspiracy theory ready to go",
]

POINTS = {
    "profile_complete": 10,
    "like": 2,
    "match": 15,
    "friendquestion_pair": 5,
    "anonymous_submit": 3,
    "smashpass_vote": 1,
}

# Badges: (threshold, icon, label). Checked highest-first.
POINT_BADGES = [
    (1000, "👑", "1000 points"),
    (500, "💎", "500 points"),
    (250, "🏆", "250 points"),
    (100, "💯", "100 points"),
    (50, "⭐", "50 points"),
    (10, "✨", "10 points"),
]

STREAK_BADGES = [
    (30, "🔥🔥🔥", "30-day streak"),
    (14, "🔥🔥", "14-day streak"),
    (7, "🔥", "7-day streak"),
    (3, "🕯️", "3-day streak"),
]

DEFAULT_REMINDER_MESSAGE = (
    "Come play a round! Check for new matches, vote on Smash or Pass, or "
    "send something for Anonymous Night. ✨"
)

# Conversation states
(
    VERIFY_CODE,
    SET_GENDER,
    SET_INTERESTED_IN,
    ANSWER_BIO,
    ANSWER_LOOKING_FOR,
    ANSWER_Q1,
    ANSWER_Q2,
    ANSWER_Q3,
    REPORT_REASON,
    PHOTO_CHOOSE_MATCH,
    PHOTO_WAIT_UPLOAD,
    ANON_MESSAGE_WAIT,
) = range(12)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small helpers so the same handlers work whether triggered by a typed
# command or a tap on a menu button
# ---------------------------------------------------------------------------

async def ack(update: Update):
    """Acknowledge a callback-button tap (no-op for typed commands)."""
    if update.callback_query:
        await update.callback_query.answer()


async def reply_to(update: Update, context: ContextTypes.DEFAULT_TYPE, text, **kwargs):
    """Reply whether the update came from a typed message or a menu button."""
    if update.message:
        await update.message.reply_text(text, **kwargs)
    else:
        await update.callback_query.message.reply_text(text, **kwargs)


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
                InlineKeyboardButton("🔎 Browse", callback_data="menu_browse"),
            ],
            [
                InlineKeyboardButton("💌 Matches", callback_data="menu_matches"),
                InlineKeyboardButton("📸 Share Photo", callback_data="menu_sharephoto"),
            ],
            [
                InlineKeyboardButton("🌙 Anonymous Night", callback_data="menu_anonymous"),
                InlineKeyboardButton("🤝 Friendship Qs", callback_data="menu_friendquestion"),
            ],
            [
                InlineKeyboardButton("😏 Smash or Pass", callback_data="menu_smashpass"),
                InlineKeyboardButton("🚩 Report", callback_data="menu_report"),
            ],
            [
                InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard"),
                InlineKeyboardButton("❓ Help", callback_data="menu_help"),
            ],
        ]
    )

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            verified INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            gender TEXT,
            interested_in TEXT,
            bio TEXT,
            looking_for TEXT,
            q1 TEXT, q2 TEXT, q3 TEXT,
            profile_complete INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS photo_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_id INTEGER,
            target_id INTEGER,
            file_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS access_codes (
            code TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0,
            used_by INTEGER,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS likes (
            liker_id INTEGER,
            liked_id INTEGER,
            created_at TEXT,
            PRIMARY KEY (liker_id, liked_id)
        );

        CREATE TABLE IF NOT EXISTS matches (
            user1_id INTEGER,
            user2_id INTEGER,
            created_at TEXT,
            PRIMARY KEY (user1_id, user2_id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reported_id INTEGER,
            reason TEXT,
            resolved INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS anon_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS friend_queue (
            telegram_id INTEGER PRIMARY KEY,
            joined_at TEXT
        );

        CREATE TABLE IF NOT EXISTS friend_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER,
            user2_id INTEGER,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS activity (
            telegram_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_active TEXT
        );

        CREATE TABLE IF NOT EXISTS smash_pass_votes (
            telegram_id INTEGER,
            prompt_id INTEGER,
            vote TEXT,
            created_at TEXT,
            PRIMARY KEY (telegram_id, prompt_id)
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('anon_night_open', '1')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('reminder_enabled', '1')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('reminder_time', '18:00')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('reminder_message', ?)",
        (DEFAULT_REMINDER_MESSAGE,),
    )
    conn.commit()
    conn.close()


def get_user(telegram_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row


def upsert_user(telegram_id, **fields):
    conn = db()
    existing = conn.execute(
        "SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    if existing:
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE users SET {cols} WHERE telegram_id = ?",
            (*fields.values(), telegram_id),
        )
    else:
        cols = ", ".join(["telegram_id", *fields.keys(), "created_at"])
        placeholders = ", ".join(["?"] * (len(fields) + 2))
        conn.execute(
            f"INSERT INTO users ({cols}) VALUES ({placeholders})",
            (telegram_id, *fields.values(), datetime.utcnow().isoformat()),
        )
    conn.commit()
    conn.close()


def is_admin(telegram_id):
    return telegram_id in ADMIN_IDS


def get_setting(key, default=None):
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def award_points(telegram_id, amount):
    """Add points and update the daily streak. Returns before/after values
    so callers can detect newly-crossed badge thresholds."""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    conn = db()
    row = conn.execute(
        "SELECT * FROM activity WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()

    prev_points = row["points"] if row else 0
    prev_streak = row["streak"] if row else 0

    if row:
        if row["last_active"] == today:
            new_streak = row["streak"]
        elif row["last_active"] == yesterday:
            new_streak = row["streak"] + 1
        else:
            new_streak = 1
        conn.execute(
            "UPDATE activity SET points = points + ?, streak = ?, last_active = ? "
            "WHERE telegram_id = ?",
            (amount, new_streak, today, telegram_id),
        )
    else:
        new_streak = 1
        conn.execute(
            "INSERT INTO activity (telegram_id, points, streak, last_active) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, amount, new_streak, today),
        )
    conn.commit()
    conn.close()

    return {
        "points": prev_points + amount,
        "streak": new_streak,
        "prev_points": prev_points,
        "prev_streak": prev_streak,
    }


def highest_badge(value, table):
    for threshold, icon, label in table:
        if value >= threshold:
            return icon, label
    return None, None


def badge_icons(points, streak):
    icons = []
    s_icon, _ = highest_badge(streak, STREAK_BADGES)
    p_icon, _ = highest_badge(points, POINT_BADGES)
    if s_icon:
        icons.append(s_icon)
    if p_icon:
        icons.append(p_icon)
    return (" " + " ".join(icons)) if icons else ""


async def award_and_notify(context: ContextTypes.DEFAULT_TYPE, telegram_id, amount):
    """award_points, plus a DM if this action crossed a new badge threshold."""
    result = award_points(telegram_id, amount)
    newly = []

    _, prev_p_label = highest_badge(result["prev_points"], POINT_BADGES)
    p_icon, new_p_label = highest_badge(result["points"], POINT_BADGES)
    if new_p_label and new_p_label != prev_p_label:
        newly.append(f"{p_icon} {new_p_label}")

    _, prev_s_label = highest_badge(result["prev_streak"], STREAK_BADGES)
    s_icon, new_s_label = highest_badge(result["streak"], STREAK_BADGES)
    if new_s_label and new_s_label != prev_s_label:
        newly.append(f"{s_icon} {new_s_label}")

    if newly:
        try:
            await context.bot.send_message(
                telegram_id,
                "🎖️ New badge unlocked: " + ", ".join(newly) + "!\nCheck /leaderboard.",
            )
        except Exception:
            logger.warning("Could not send badge notification to %s", telegram_id)

    return result


def get_activity(telegram_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM activity WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Access code gating (bridges the WhatsApp group -> Telegram bot)
# ---------------------------------------------------------------------------

async def gencode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: generate a one-time access code to post in the WhatsApp group."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for DTZ TRIO admins only.")
        return
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = db()
    conn.execute(
        "INSERT INTO access_codes (code, created_at) VALUES (?, ?)",
        (code, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"New one-time access code:\n\n`{code}`\n\n"
        f"Post this in the WhatsApp group. Members DM the bot with /start "
        f"and enter this code to unlock it.",
        parse_mode="Markdown",
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user and user["banned"]:
        await update.message.reply_text("Your access to this bot has been revoked.")
        return ConversationHandler.END

    if user and user["verified"]:
        await update.message.reply_text(
            "Welcome back to DTZ TRIO! 🎉\n\n"
            "Every game you play earns points and builds your daily streak — "
            "check /leaderboard to see where you stand.\n\n"
            "Tap below to jump in:",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Welcome to the DTZ TRIO Bot 🎉\n\n"
        "This bot is only for DTZ TRIO members. Please enter the access "
        "code posted in the WhatsApp group."
    )
    return VERIFY_CODE


async def verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    conn = db()
    row = conn.execute(
        "SELECT * FROM access_codes WHERE code = ? AND used = 0", (code,)
    ).fetchone()
    if not row:
        conn.close()
        await update.message.reply_text(
            "That code isn't valid or has already been used. Double-check "
            "the WhatsApp group for the current code, or ask an admin."
        )
        return VERIFY_CODE

    conn.execute(
        "UPDATE access_codes SET used = 1, used_by = ? WHERE code = ?",
        (update.effective_user.id, code),
    )
    conn.commit()
    conn.close()

    tg_user = update.effective_user
    upsert_user(
        tg_user.id,
        username=tg_user.username or "",
        first_name=tg_user.first_name or "",
        verified=1,
    )
    await update.message.reply_text(
        "You're verified! Let's set up your profile.\n\nWhat's your gender?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Male", callback_data="gender_male"),
                    InlineKeyboardButton("Female", callback_data="gender_female"),
                ]
            ]
        ),
    )
    return SET_GENDER


# ---------------------------------------------------------------------------
# Profile creation
# ---------------------------------------------------------------------------

async def profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    user = get_user(update.effective_user.id)
    if not user or not user["verified"]:
        await reply_to(update, context, "Please /start and enter your access code first.")
        return ConversationHandler.END
    if user["banned"]:
        await reply_to(update, context, "Your access to this bot has been revoked.")
        return ConversationHandler.END

    await reply_to(
        update,
        context,
        "Let's (re)build your profile. What's your gender?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Male", callback_data="gender_male"),
                    InlineKeyboardButton("Female", callback_data="gender_female"),
                ]
            ]
        ),
    )
    return SET_GENDER


async def set_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gender = "male" if query.data == "gender_male" else "female"
    upsert_user(update.effective_user.id, gender=gender)
    await query.edit_message_text(
        f"Gender set to {gender}. Who are you interested in matching with?",
    )
    await query.message.reply_text(
        "Who would you like to browse?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Men", callback_data="interest_male"),
                    InlineKeyboardButton("Women", callback_data="interest_female"),
                ],
                [InlineKeyboardButton("Both", callback_data="interest_both")],
            ]
        ),
    )
    return SET_INTERESTED_IN


async def set_interested_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mapping = {
        "interest_male": "male",
        "interest_female": "female",
        "interest_both": "both",
    }
    upsert_user(update.effective_user.id, interested_in=mapping[query.data])
    await query.edit_message_text(
        "Got it. Write a short bio (a sentence or two about you)."
    )
    return ANSWER_BIO


async def answer_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user.id, bio=update.message.text.strip()[:400])
    await update.message.reply_text(
        "What are you looking for?",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(opt, callback_data=f"lookingfor_{i}")]
             for i, opt in enumerate(LOOKING_FOR_OPTIONS)]
        ),
    )
    return ANSWER_LOOKING_FOR


async def answer_looking_for(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    choice = LOOKING_FOR_OPTIONS[idx]
    upsert_user(update.effective_user.id, looking_for=choice)
    await query.edit_message_text(
        f"Looking for: {choice}. Now a few quick icebreakers so people get a "
        f"sense of you.\n\nQ1: {ICEBREAKERS[0]}"
    )
    return ANSWER_Q1


async def answer_q1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user.id, q1=update.message.text.strip()[:300])
    await update.message.reply_text(f"Q2: {ICEBREAKERS[1]}")
    return ANSWER_Q2


async def answer_q2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user.id, q2=update.message.text.strip()[:300])
    await update.message.reply_text(f"Q3: {ICEBREAKERS[2]}")
    return ANSWER_Q3


async def answer_q3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(
        update.effective_user.id,
        q3=update.message.text.strip()[:300],
        profile_complete=1,
    )
    await award_and_notify(context, update.effective_user.id, POINTS["profile_complete"])
    await update.message.reply_text(
        f"Profile complete! +{POINTS['profile_complete']} points 🎉\n\n"
        f"What's next?",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Browsing & matching
# ---------------------------------------------------------------------------

def next_profile_for(viewer_id):
    """Return the next unseen, opposite/matching-preference profile."""
    viewer = get_user(viewer_id)
    conn = db()

    if viewer["interested_in"] == "both":
        gender_filter = "1=1"
    else:
        gender_filter = "gender = ?"

    params = [viewer_id, viewer_id]
    query = f"""
        SELECT * FROM users
        WHERE telegram_id != ?
          AND profile_complete = 1
          AND banned = 0
          AND {gender_filter}
          AND telegram_id NOT IN (
              SELECT liked_id FROM likes WHERE liker_id = ?
          )
        ORDER BY RANDOM() LIMIT 1
    """
    if viewer["interested_in"] != "both":
        params.insert(1, viewer["interested_in"])
        # reorder: gender param goes before the two telegram_id excludes in SQL text above
        row = conn.execute(
            f"""
            SELECT * FROM users
            WHERE telegram_id != ?
              AND profile_complete = 1
              AND banned = 0
              AND gender = ?
              AND telegram_id NOT IN (
                  SELECT liked_id FROM likes WHERE liker_id = ?
              )
            ORDER BY RANDOM() LIMIT 1
            """,
            (viewer_id, viewer["interested_in"], viewer_id),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM users
            WHERE telegram_id != ?
              AND profile_complete = 1
              AND banned = 0
              AND telegram_id NOT IN (
                  SELECT liked_id FROM likes WHERE liker_id = ?
              )
            ORDER BY RANDOM() LIMIT 1
            """,
            (viewer_id, viewer_id),
        ).fetchone()
    conn.close()
    return row


async def browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    user = get_user(update.effective_user.id)
    if not user or not user["verified"]:
        await reply_to(update, context, "Please /start and enter your access code first.")
        return
    if user["banned"]:
        await reply_to(update, context, "Your access to this bot has been revoked.")
        return
    if not user["profile_complete"]:
        await reply_to(update, context, "Set up your profile first with /profile.")
        return

    await send_next_profile(update.effective_chat.id, update.effective_user.id, context)


async def send_next_profile(chat_id, viewer_id, context: ContextTypes.DEFAULT_TYPE):
    profile = next_profile_for(viewer_id)
    if not profile:
        await context.bot.send_message(
            chat_id, "No new profiles right now — check back later!"
        )
        return

    text = (
        f"👤 Anonymous DTZ TRIO member ({profile['gender']})\n\n"
        f"Bio: {profile['bio']}\n"
        f"Looking for: {profile['looking_for']}\n\n"
        f"Q: {ICEBREAKERS[0]}\nA: {profile['q1']}\n\n"
        f"Q: {ICEBREAKERS[1]}\nA: {profile['q2']}\n\n"
        f"Q: {ICEBREAKERS[2]}\nA: {profile['q3']}\n\n"
        f"No photo is shared here — photos are only exchanged after a match, "
        f"and only if both people agree."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👍 Like", callback_data=f"like_{profile['telegram_id']}"),
                InlineKeyboardButton("➡️ Skip", callback_data=f"skip_{profile['telegram_id']}"),
            ]
        ]
    )
    await context.bot.send_message(chat_id, text, reply_markup=keyboard)


async def handle_like_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, target_id = query.data.split("_")
    target_id = int(target_id)
    liker_id = update.effective_user.id

    if action == "like":
        conn = db()
        conn.execute(
            "INSERT OR IGNORE INTO likes (liker_id, liked_id, created_at) VALUES (?, ?, ?)",
            (liker_id, target_id, datetime.utcnow().isoformat()),
        )
        mutual = conn.execute(
            "SELECT 1 FROM likes WHERE liker_id = ? AND liked_id = ?",
            (target_id, liker_id),
        ).fetchone()
        conn.commit()
        conn.close()
        await award_and_notify(context, liker_id, POINTS["like"])

        if mutual:
            u1, u2 = sorted([liker_id, target_id])
            conn = db()
            conn.execute(
                "INSERT OR IGNORE INTO matches (user1_id, user2_id, created_at) VALUES (?, ?, ?)",
                (u1, u2, datetime.utcnow().isoformat()),
            )
            conn.commit()
            conn.close()
            await award_and_notify(context, liker_id, POINTS["match"])
            await award_and_notify(context, target_id, POINTS["match"])

            liker = get_user(liker_id)
            target = get_user(target_id)
            liker_handle = f"@{liker['username']}" if liker["username"] else "(no username set — ask them to set one in Telegram settings)"
            target_handle = f"@{target['username']}" if target["username"] else "(no username set — ask them to set one in Telegram settings)"

            await context.bot.send_message(
                target_id,
                f"🎉 It's a match! You and {liker_handle} both liked each other.\n"
                f"Say hi: {liker_handle}\n\n+{POINTS['match']} points!",
            )
            await context.bot.send_message(
                liker_id,
                f"🎉 It's a match! You and {target_handle} both liked each other.\n"
                f"Say hi: {target_handle}\n\n+{POINTS['match']} points!",
            )

    await query.edit_message_reply_markup(reply_markup=None)
    await send_next_profile(update.effective_chat.id, liker_id, context)


async def matches_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    uid = update.effective_user.id
    conn = db()
    rows = conn.execute(
        "SELECT * FROM matches WHERE user1_id = ? OR user2_id = ?", (uid, uid)
    ).fetchall()
    conn.close()
    if not rows:
        await reply_to(update, context, "No matches yet — keep browsing! Tap 🔎 Browse in /menu.")
        return
    lines = []
    for r in rows:
        other_id = r["user2_id"] if r["user1_id"] == uid else r["user1_id"]
        other = get_user(other_id)
        handle = f"@{other['username']}" if other["username"] else f"(id {other_id}, no username)"
        lines.append(handle)
    await reply_to(update, context, "Your matches:\n" + "\n".join(lines))


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conn = db()
    conn.execute("DELETE FROM users WHERE telegram_id = ?", (uid,))
    conn.execute("DELETE FROM likes WHERE liker_id = ? OR liked_id = ?", (uid, uid))
    conn.execute("DELETE FROM matches WHERE user1_id = ? OR user2_id = ?", (uid, uid))
    conn.commit()
    conn.close()
    await update.message.reply_text("You've been opted out and your data was deleted.")


# ---------------------------------------------------------------------------
# Consent-gated photo sharing (only available after a mutual match)
# ---------------------------------------------------------------------------

def get_matches_for(uid):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM matches WHERE user1_id = ? OR user2_id = ?", (uid, uid)
    ).fetchall()
    conn.close()
    return [r["user2_id"] if r["user1_id"] == uid else r["user1_id"] for r in rows]


async def sharephoto_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    uid = update.effective_user.id
    match_ids = get_matches_for(uid)
    if not match_ids:
        await reply_to(
            update,
            context,
            "You don't have any matches yet. Photo sharing is only available "
            "with someone you've matched with.",
        )
        return ConversationHandler.END

    buttons = []
    for other_id in match_ids:
        other = get_user(other_id)
        label = f"@{other['username']}" if other["username"] else f"Match {other_id}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"phototarget_{other_id}")])

    await reply_to(
        update,
        context,
        "Who would you like to share a photo with? They'll be asked to "
        "consent before they see it.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return PHOTO_CHOOSE_MATCH


async def sharephoto_choose_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.split("_")[1])
    context.user_data["photo_target"] = target_id
    await query.edit_message_text("Go ahead and send the photo now.")
    return PHOTO_WAIT_UPLOAD


async def sharephoto_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Please send an actual photo, or /cancel.")
        return PHOTO_WAIT_UPLOAD

    requester_id = update.effective_user.id
    target_id = context.user_data.get("photo_target")
    file_id = update.message.photo[-1].file_id

    conn = db()
    cur = conn.execute(
        "INSERT INTO photo_requests (requester_id, target_id, file_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (requester_id, target_id, file_id, datetime.utcnow().isoformat()),
    )
    request_id = cur.lastrowid
    conn.commit()
    conn.close()

    requester = get_user(requester_id)
    handle = f"@{requester['username']}" if requester["username"] else "Your match"

    await context.bot.send_message(
        target_id,
        f"{handle} would like to share a photo with you. Do you want to see it?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Yes, show me", callback_data=f"photoreq_accept_{request_id}"),
                    InlineKeyboardButton("❌ No thanks", callback_data=f"photoreq_decline_{request_id}"),
                ]
            ]
        ),
    )
    await update.message.reply_text(
        "Sent! They'll need to consent before they see it — you'll be notified either way."
    )
    context.user_data.pop("photo_target", None)
    return ConversationHandler.END


async def handle_photo_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, request_id = query.data.split("_")[1], int(query.data.split("_")[2])

    conn = db()
    row = conn.execute(
        "SELECT * FROM photo_requests WHERE id = ? AND status = 'pending'", (request_id,)
    ).fetchone()
    if not row:
        conn.close()
        await query.edit_message_text("This request is no longer valid.")
        return

    if action == "accept":
        conn.execute("UPDATE photo_requests SET status = 'accepted' WHERE id = ?", (request_id,))
        conn.commit()
        conn.close()
        await context.bot.send_photo(update.effective_user.id, row["file_id"])
        await query.edit_message_text("Photo shared with you.")
        await context.bot.send_message(
            row["requester_id"], "Your match agreed to see your photo and it was sent."
        )
    else:
        conn.execute("UPDATE photo_requests SET status = 'declined' WHERE id = ?", (request_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text("Declined. No photo was shared.")
        await context.bot.send_message(
            row["requester_id"], "Your match chose not to view the photo this time."
        )


# ---------------------------------------------------------------------------
# Anonymous Night — fully anonymous submissions relayed to admins only
# ---------------------------------------------------------------------------

async def anonymous_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    user = get_user(update.effective_user.id)
    if not user or not user["verified"]:
        await reply_to(update, context, "Please /start and enter your access code first.")
        return ConversationHandler.END
    if user["banned"]:
        await reply_to(update, context, "Your access to this bot has been revoked.")
        return ConversationHandler.END
    if get_setting("anon_night_open", "1") != "1":
        await reply_to(update, context, "Anonymous Night is currently closed. Check back later!")
        return ConversationHandler.END

    await reply_to(
        update,
        context,
        "🌙 Anonymous Night\n\n"
        "Write your message below. It goes straight to the DTZ TRIO admins, "
        "completely anonymously — this bot does not record or store who "
        "sent it, so it can't be traced back to you on our end.\n\n"
        "Keep it respectful: no targeted harassment, threats, or naming "
        "someone in a way meant to hurt them. Admins may close Anonymous "
        "Night for everyone if it's misused. Send /cancel to back out.",
    )
    return ANON_MESSAGE_WAIT


async def anonymous_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    content = update.message.text.strip()[:2000]

    # Note: nothing linking this content to update.effective_user.id is
    # stored or forwarded anywhere — true to the "anonymous even from
    # admins" requirement.
    conn = db()
    cur = conn.execute(
        "INSERT INTO anon_messages (content, created_at) VALUES (?, ?)",
        (content, datetime.utcnow().isoformat()),
    )
    msg_number = cur.lastrowid
    conn.commit()
    conn.close()

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🌙 Anonymous Night — submission #{msg_number}\n\n{content}",
            )
        except Exception:
            logger.warning("Could not deliver anon message to admin %s", admin_id)

    await award_and_notify(context, update.effective_user.id, POINTS["anonymous_submit"])
    await update.message.reply_text(
        f"Sent anonymously. Thanks for sharing! 🌙 +{POINTS['anonymous_submit']} points"
    )
    return ConversationHandler.END


async def nightopen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    set_setting("anon_night_open", "1")
    await update.message.reply_text("Anonymous Night is now OPEN for submissions.")


async def nightclose_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    set_setting("anon_night_open", "0")
    await update.message.reply_text("Anonymous Night is now CLOSED. No new submissions will be accepted.")


# ---------------------------------------------------------------------------
# Friendship Questions — random 1-on-1 pairing with shared discussion prompts
# ---------------------------------------------------------------------------

async def friendquestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    uid = update.effective_user.id
    user = get_user(uid)
    if not user or not user["verified"]:
        await reply_to(update, context, "Please /start and enter your access code first.")
        return
    if user["banned"]:
        await reply_to(update, context, "Your access to this bot has been revoked.")
        return

    conn = db()
    already_waiting = conn.execute(
        "SELECT 1 FROM friend_queue WHERE telegram_id = ?", (uid,)
    ).fetchone()
    if already_waiting:
        conn.close()
        await reply_to(
            update,
            context,
            "You're already in the queue — hang tight, we'll pair you with "
            "someone soon! Use /leavequeue to cancel.",
        )
        return

    partner_row = conn.execute(
        "SELECT telegram_id FROM friend_queue WHERE telegram_id != ? "
        "ORDER BY joined_at ASC LIMIT 1",
        (uid,),
    ).fetchone()

    if not partner_row:
        conn.execute(
            "INSERT INTO friend_queue (telegram_id, joined_at) VALUES (?, ?)",
            (uid, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
        await reply_to(
            update,
            context,
            "You're in the queue for Friendship Questions! We'll message "
            "you the moment someone else joins. Use /leavequeue to cancel.",
        )
        return

    partner_id = partner_row["telegram_id"]
    conn.execute("DELETE FROM friend_queue WHERE telegram_id IN (?, ?)", (uid, partner_id))
    conn.execute(
        "INSERT INTO friend_pairs (user1_id, user2_id, created_at) VALUES (?, ?, ?)",
        (uid, partner_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    await award_and_notify(context, uid, POINTS["friendquestion_pair"])
    await award_and_notify(context, partner_id, POINTS["friendquestion_pair"])

    me = get_user(uid)
    partner = get_user(partner_id)
    me_handle = f"@{me['username']}" if me["username"] else "(no username set)"
    partner_handle = f"@{partner['username']}" if partner["username"] else "(no username set)"

    questions = random.choice(FRIENDSHIP_QUESTION_SETS)
    q_text = "\n".join(f"• {q}" for q in questions)

    await context.bot.send_message(
        uid,
        f"🤝 You've been paired for Friendship Questions with {partner_handle}!\n\n"
        f"Here are some questions to break the ice — message them directly:\n\n{q_text}\n\n"
        f"+{POINTS['friendquestion_pair']} points!",
    )
    await context.bot.send_message(
        partner_id,
        f"🤝 You've been paired for Friendship Questions with {me_handle}!\n\n"
        f"Here are some questions to break the ice — message them directly:\n\n{q_text}\n\n"
        f"+{POINTS['friendquestion_pair']} points!",
    )


async def leavequeue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    uid = update.effective_user.id
    conn = db()
    removed = conn.execute("DELETE FROM friend_queue WHERE telegram_id = ?", (uid,)).rowcount
    conn.commit()
    conn.close()
    if removed:
        await reply_to(update, context, "You've left the Friendship Questions queue.")
    else:
        await reply_to(update, context, "You're not currently in the queue.")


# ---------------------------------------------------------------------------
# Smash or Pass — playful, anonymized prompts (never real member photos)
# ---------------------------------------------------------------------------

async def smashpass_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    uid = update.effective_user.id
    user = get_user(uid)
    if not user or not user["verified"]:
        await reply_to(update, context, "Please /start and enter your access code first.")
        return
    if user["banned"]:
        await reply_to(update, context, "Your access to this bot has been revoked.")
        return

    conn = db()
    voted = {
        r["prompt_id"]
        for r in conn.execute(
            "SELECT prompt_id FROM smash_pass_votes WHERE telegram_id = ?", (uid,)
        ).fetchall()
    }
    conn.close()

    available = [i for i in range(len(SMASH_PASS_PROMPTS)) if i not in voted]
    if not available:
        await reply_to(
            update,
            context,
            "You've voted on every prompt we've got! 😏 New ones coming soon.",
            reply_markup=main_menu_keyboard(),
        )
        return

    idx = random.choice(available)
    await reply_to(
        update,
        context,
        f"😏 Smash or Pass:\n\n\"{SMASH_PASS_PROMPTS[idx]}\"",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("💥 Smash", callback_data=f"sp_smash_{idx}"),
                    InlineKeyboardButton("🚫 Pass", callback_data=f"sp_pass_{idx}"),
                ]
            ]
        ),
    )


async def handle_smashpass_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, vote, idx_str = query.data.split("_")
    idx = int(idx_str)
    uid = update.effective_user.id

    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO smash_pass_votes (telegram_id, prompt_id, vote, created_at) "
        "VALUES (?, ?, ?, ?)",
        (uid, idx, vote, datetime.utcnow().isoformat()),
    )
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) c FROM smash_pass_votes WHERE prompt_id = ?", (idx,)
    ).fetchone()["c"]
    smashes = conn.execute(
        "SELECT COUNT(*) c FROM smash_pass_votes WHERE prompt_id = ? AND vote = 'smash'", (idx,)
    ).fetchone()["c"]
    conn.close()

    await award_and_notify(context, uid, POINTS["smashpass_vote"])
    pct_smash = round(100 * smashes / total) if total else 0

    await query.edit_message_text(
        f"You voted {'💥 Smash' if vote == 'smash' else '🚫 Pass'}! "
        f"+{POINTS['smashpass_vote']} point\n\n"
        f"Community so far: {pct_smash}% Smash / {100 - pct_smash}% Pass "
        f"({total} vote{'s' if total != 1 else ''})",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("➡️ Next prompt", callback_data="menu_smashpass")]]
        ),
    )


# ---------------------------------------------------------------------------
# Leaderboard, help, and the /menu entry point
# ---------------------------------------------------------------------------

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    conn = db()
    top = conn.execute(
        "SELECT * FROM activity ORDER BY points DESC LIMIT 10"
    ).fetchall()
    conn.close()

    if not top:
        await reply_to(
            update,
            context,
            "No activity yet — be the first on the board! Tap a game in /menu.",
        )
        return

    lines = []
    for i, r in enumerate(top, 1):
        u = get_user(r["telegram_id"])
        name = (u["first_name"] if u and u["first_name"] else None) or "A DTZ TRIO member"
        icons = badge_icons(r["points"], r["streak"])
        lines.append(f"{i}. {name}{icons} — {r['points']} pts (🔥{r['streak']}d streak)")

    me = get_activity(update.effective_user.id)
    footer = ""
    if me:
        my_icons = badge_icons(me["points"], me["streak"])
        footer = f"\n\nYour stats: {me['points']} pts, 🔥{me['streak']}-day streak{my_icons}"

    await reply_to(update, context, "🏆 DTZ TRIO Leaderboard\n\n" + "\n".join(lines) + footer)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    user = get_user(update.effective_user.id)
    if not user or not user["verified"]:
        await reply_to(update, context, "Please /start and enter your access code first.")
        return

    await reply_to(
        update,
        context,
        "✨ DTZ TRIO Bot — everything in one place:\n\n"
        "👤 /profile — create or edit your profile\n"
        "🔎 /browse — browse profiles\n"
        "💌 /matches — see your matches\n"
        "📸 /sharephoto — share a photo with a match (they must consent)\n"
        "🌙 /anonymous — send an anonymous message to admins\n"
        "🤝 /friendquestion — get paired for Friendship Questions\n"
        "😏 /smashpass — vote on fun prompts\n"
        "🏆 /leaderboard — see the points leaderboard\n"
        "🚩 /report — report abusive behavior\n"
        "🛑 /stop — opt out and delete your data\n\n"
        "Every game earns points and builds your daily streak!",
        reply_markup=main_menu_keyboard(),
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    user = get_user(update.effective_user.id)
    if not user or not user["verified"]:
        await reply_to(update, context, "Please /start and enter your access code first.")
        return
    if user["banned"]:
        await reply_to(update, context, "Your access to this bot has been revoked.")
        return
    await reply_to(
        update, context, "✨ DTZ TRIO Bot — what would you like to do?", reply_markup=main_menu_keyboard()
    )


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes taps on the main menu's non-conversation buttons."""
    data = update.callback_query.data
    if data == "menu_browse":
        await browse(update, context)
    elif data == "menu_matches":
        await matches_cmd(update, context)
    elif data == "menu_friendquestion":
        await friendquestion_start(update, context)
    elif data == "menu_smashpass":
        await smashpass_start(update, context)
    elif data == "menu_leaderboard":
        await leaderboard_cmd(update, context)
    elif data == "menu_help":
        await help_cmd(update, context)


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text = " ".join(context.args)
    conn = db()
    rows = conn.execute(
        "SELECT telegram_id FROM users WHERE verified = 1 AND banned = 0"
    ).fetchall()
    conn.close()

    sent = 0
    for r in rows:
        try:
            await context.bot.send_message(
                r["telegram_id"], f"📢 DTZ TRIO Announcement:\n\n{text}"
            )
            sent += 1
        except Exception:
            logger.warning("Could not deliver broadcast to %s", r["telegram_id"])

    await update.message.reply_text(f"Broadcast sent to {sent} member(s).")


# ---------------------------------------------------------------------------
# Scheduled daily reminder — automatic nudges instead of admin-triggered only
# ---------------------------------------------------------------------------

async def send_daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback: sends the configured nudge to every verified,
    non-banned member. Runs automatically once a day; can also be fired
    on demand via /remindernow."""
    message = get_setting("reminder_message", DEFAULT_REMINDER_MESSAGE)
    conn = db()
    rows = conn.execute(
        "SELECT telegram_id FROM users WHERE verified = 1 AND banned = 0"
    ).fetchall()
    conn.close()

    sent = 0
    for r in rows:
        try:
            await context.bot.send_message(
                r["telegram_id"],
                f"⏰ Daily nudge:\n\n{message}",
                reply_markup=main_menu_keyboard(),
            )
            sent += 1
        except Exception:
            logger.warning("Could not deliver reminder to %s", r["telegram_id"])
    logger.info("Daily reminder sent to %s member(s)", sent)


def schedule_daily_reminder(app: Application):
    """(Re)schedules the daily reminder job based on current settings.
    Safe to call repeatedly (e.g. after /setreminder changes the time)."""
    if not app.job_queue:
        logger.warning(
            "JobQueue not available — install with: "
            'pip install "python-telegram-bot[job-queue]" '
            "to enable automatic daily reminders. Falling back to "
            "admin-triggered /broadcast and /remindernow only."
        )
        return

    for job in app.job_queue.get_jobs_by_name("daily_reminder"):
        job.schedule_removal()

    if get_setting("reminder_enabled", "1") != "1":
        logger.info("Daily reminder is disabled (reminder_enabled=0).")
        return

    time_str = get_setting("reminder_time", "18:00")
    try:
        hour, minute = (int(x) for x in time_str.split(":"))
    except ValueError:
        hour, minute = 18, 0

    app.job_queue.run_daily(
        send_daily_reminder, time=dt_time(hour=hour, minute=minute), name="daily_reminder"
    )
    logger.info("Daily reminder scheduled for %02d:%02d (server local time)", hour, minute)


async def setreminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /setreminder HH:MM Your message here\n"
            "Example: /setreminder 18:00 Don't forget to check today's Anonymous Night!\n\n"
            "Time is in 24-hour format, server local time."
        )
        return

    time_str = context.args[0]
    try:
        hour, minute = (int(x) for x in time_str.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Time must be HH:MM 24-hour format, e.g. 18:00")
        return

    message_text = " ".join(context.args[1:])
    set_setting("reminder_time", f"{hour:02d}:{minute:02d}")
    set_setting("reminder_message", message_text)
    set_setting("reminder_enabled", "1")
    schedule_daily_reminder(context.application)

    await update.message.reply_text(
        f"Daily reminder set for {hour:02d}:{minute:02d} (server local time):\n\n{message_text}"
    )


async def reminderon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    set_setting("reminder_enabled", "1")
    schedule_daily_reminder(context.application)
    await update.message.reply_text("Daily reminder turned ON.")


async def reminderoff_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    set_setting("reminder_enabled", "0")
    schedule_daily_reminder(context.application)
    await update.message.reply_text("Daily reminder turned OFF.")


async def remindernow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    await send_daily_reminder(context)
    await update.message.reply_text("Reminder sent to all verified members.")


# ---------------------------------------------------------------------------
# Reporting & admin moderation (ties back to abuse handling on YOUR platform)
# ---------------------------------------------------------------------------

async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    await reply_to(
        update,
        context,
        "To report someone, send their @username or the number shown when "
        "you matched. Include a short reason. Format:\n\n@username reason here",
    )
    return REPORT_REASON


async def report_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Please include a reason, e.g. '@someone was sending scam links'.")
        return REPORT_REASON

    target_handle, reason = parts[0].lstrip("@"), parts[1]
    conn = db()
    target = conn.execute(
        "SELECT telegram_id FROM users WHERE username = ?", (target_handle,)
    ).fetchone()
    target_id = target["telegram_id"] if target else None
    conn.execute(
        "INSERT INTO reports (reporter_id, reported_id, reason, created_at) VALUES (?, ?, ?, ?)",
        (update.effective_user.id, target_id, reason, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text("Report submitted. A DTZ TRIO admin will review it.")

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"⚠️ New report\nAgainst: @{target_handle} (id: {target_id})\n"
                f"From: {update.effective_user.id}\nReason: {reason}\n\n"
                f"To ban: /ban {target_id}",
            )
        except Exception:
            logger.warning("Could not notify admin %s", admin_id)

    return ConversationHandler.END


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("telegram_id must be a number.")
        return

    upsert_user(target_id, banned=1)
    conn = db()
    conn.execute(
        "UPDATE reports SET resolved = 1 WHERE reported_id = ?", (target_id,)
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"User {target_id} has been banned from the bot.")
    try:
        await context.bot.send_message(
            target_id, "You have been banned from the DTZ TRIO Matchmaking Bot by an admin."
        )
    except Exception:
        pass


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("telegram_id must be a number.")
        return
    upsert_user(target_id, banned=0)
    await update.message.reply_text(f"User {target_id} has been unbanned.")


async def reports_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    conn = db()
    rows = conn.execute(
        "SELECT * FROM reports WHERE resolved = 0 ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No open reports.")
        return
    lines = [
        f"#{r['id']} — reported_id: {r['reported_id']} — {r['reason']}" for r in rows
    ]
    await update.message.reply_text("Open reports:\n" + "\n".join(lines))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return
    conn = db()
    total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    complete = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE profile_complete = 1"
    ).fetchone()["c"]
    matches = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    banned = conn.execute("SELECT COUNT(*) c FROM users WHERE banned = 1").fetchone()["c"]
    conn.close()
    await update.message.reply_text(
        f"Users: {total}\nComplete profiles: {complete}\nMatches: {matches}\nBanned: {banned}"
    )


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        raise SystemExit("Set the BOT_TOKEN environment variable before running.")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    profile_states = {
        SET_GENDER: [CallbackQueryHandler(set_gender, pattern="^gender_")],
        SET_INTERESTED_IN: [CallbackQueryHandler(set_interested_in, pattern="^interest_")],
        ANSWER_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_bio)],
        ANSWER_LOOKING_FOR: [CallbackQueryHandler(answer_looking_for, pattern="^lookingfor_")],
        ANSWER_Q1: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q1)],
        ANSWER_Q2: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q2)],
        ANSWER_Q3: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q3)],
    }

    verify_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={VERIFY_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_code)], **profile_states},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    profile_conv = ConversationHandler(
        entry_points=[
            CommandHandler("profile", profile_start),
            CallbackQueryHandler(profile_start, pattern="^menu_profile$"),
        ],
        states=profile_states,
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    report_conv = ConversationHandler(
        entry_points=[
            CommandHandler("report", report_start),
            CallbackQueryHandler(report_start, pattern="^menu_report$"),
        ],
        states={REPORT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_submit)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    sharephoto_conv = ConversationHandler(
        entry_points=[
            CommandHandler("sharephoto", sharephoto_start),
            CallbackQueryHandler(sharephoto_start, pattern="^menu_sharephoto$"),
        ],
        states={
            PHOTO_CHOOSE_MATCH: [CallbackQueryHandler(sharephoto_choose_target, pattern="^phototarget_")],
            PHOTO_WAIT_UPLOAD: [MessageHandler(filters.PHOTO, sharephoto_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    anonymous_conv = ConversationHandler(
        entry_points=[
            CommandHandler("anonymous", anonymous_start),
            CallbackQueryHandler(anonymous_start, pattern="^menu_anonymous$"),
        ],
        states={
            ANON_MESSAGE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, anonymous_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(verify_conv)
    app.add_handler(profile_conv)
    app.add_handler(report_conv)
    app.add_handler(sharephoto_conv)
    app.add_handler(anonymous_conv)
    app.add_handler(CommandHandler("browse", browse))
    app.add_handler(CommandHandler("matches", matches_cmd))
    app.add_handler(CommandHandler("friendquestion", friendquestion_start))
    app.add_handler(CommandHandler("leavequeue", leavequeue_cmd))
    app.add_handler(CommandHandler("smashpass", smashpass_start))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("gencode", gencode))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("reports", reports_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("nightopen", nightopen_cmd))
    app.add_handler(CommandHandler("nightclose", nightclose_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("setreminder", setreminder_cmd))
    app.add_handler(CommandHandler("reminderon", reminderon_cmd))
    app.add_handler(CommandHandler("reminderoff", reminderoff_cmd))
    app.add_handler(CommandHandler("remindernow", remindernow_cmd))
    app.add_handler(CallbackQueryHandler(handle_like_skip, pattern="^(like|skip)_"))
    app.add_handler(CallbackQueryHandler(handle_photo_consent, pattern="^photoreq_"))
    app.add_handler(CallbackQueryHandler(handle_smashpass_vote, pattern="^sp_(smash|pass)_"))
    app.add_handler(
        CallbackQueryHandler(
            menu_router,
            pattern="^menu_(browse|matches|friendquestion|smashpass|leaderboard|help)$",
        )
    )

    schedule_daily_reminder(app)

    logger.info("DTZ TRIO Matchmaking Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
