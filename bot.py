# =========================
# IMPORT
# =========================

import os
import re
import secrets
import string
import asyncpg
import time

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument
)

from aiogram.exceptions import TelegramBadRequest

# =========================
# CONFIG
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

CHANNEL_DB = os.getenv("CHANNEL_DB")
ADMINS = set(
    int(x)
    for x in os.getenv("ADMINS", "").split(",")
    if x.strip().isdigit()
)

FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL")
NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL")
VIP_LINK = os.getenv("VIP_LINK")

# =========================
# DB POOL
# =========================

db_pool: asyncpg.Pool | None = None

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,

        min_size=1,
        max_size=10,

        statement_cache_size=0,
        command_timeout=60
    )

    async with db_pool.acquire() as conn:

        await conn.execute("""

        CREATE TABLE IF NOT EXISTS users(
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            fullname TEXT
        );

        CREATE TABLE IF NOT EXISTS codes(
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE,
            owner_id BIGINT,
            total_media INT,
            total_size BIGINT
        );

        CREATE TABLE IF NOT EXISTS medias(
            id SERIAL PRIMARY KEY,
            code TEXT,
            file_id TEXT,
            file_type TEXT,
            file_size BIGINT
        );
        """)
# =========================
# CACHE
# =========================

cooldown = {
    "global": {},   # user_id -> last click
    "page": {},     # (user_id, page) -> last open
}
page_history = {}  # user_id -> {page: last_open_time}
page_cooldown = {}  # user_id -> last_switch_time
user_click_lock = {}
upload_sessions = {}
user_states = {}
last_edit_time = {}

# =========================
# ROUTER
# =========================

router = Router()

# =========================
# KEYBOARD
# =========================

def get_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📤 Up File"),
                KeyboardButton(text="📥 Get File")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Upload atau ambil file... jangan bingung 😏"
    )
# =========================
# FORCE SUB
# =========================

async def check_force_sub(
    bot: Bot,
    user_id: int,
    channel: str
):

    try:

        ch = channel.replace("@", "")

        member = await bot.get_chat_member(
            f"@{ch}",
            user_id
        )

        return member.status in [
            "member",
            "administrator",
            "creator"
        ]

    except Exception:

        return False


def force_kb(channel):

    ch = channel.replace("@", "")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Join",
                    url=f"https://t.me/{ch}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Check",
                    callback_data="check_sub"
                )
            ]
        ]
    )
# =========================
# START
# =========================

@router.message(F.text == "/start")
async def start(message: Message, bot: Bot):

    user = message.from_user

    # FORCE SUB FIRST (lebih efisien)
    if FORCE_CHANNEL:
        ok = await check_force_sub(bot, user.id, FORCE_CHANNEL)

        if not ok:
            return await message.answer(
                "⚠️ ACCESS BLOCKED\n\n"
                "😏 Kamu belum join channel.\n"
                "Join dulu, baru bisa pakai bot.",
                reply_markup=force_kb(FORCE_CHANNEL)
            )

    # SAVE USER (safe)
    try:
        await add_user(
            user.id,
            user.username or "none",
            user.full_name
        )
    except Exception:
        pass

    # RESPONSE
    await message.answer(
        "🔥 BOT ONLINE\n\n"
        "😏 Selamat datang di FILE CODE SYSTEM.\n\n"
        "━━━━━━━━━━━━━━\n"
        "📌 MENU\n"
        "━━━━━━━━━━━━━━\n"
        "📤 Up File → upload file\n"
        "📥 Get File → ambil file pakai CODE\n\n"
        "━━━━━━━━━━━━━━\n"
        "💀 NOTE\n"
        "━━━━━━━━━━━━━━\n"
        "• Bot tidak peduli kamu salah input\n"
        "• CODE hilang = tanggung jawab user\n"
        "• Jangan spam, nanti dibatasi 😌",
        reply_markup=get_keyboard()
    )
# =========================
# CHECK SUB
# =========================

@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery, bot: Bot):

    if not FORCE_CHANNEL:
        return await call.answer("Force sub OFF", show_alert=True)

    ok = await check_force_sub(
        bot,
        call.from_user.id,
        FORCE_CHANNEL
    )

    if not ok:
        return await call.answer(
            "❌ Kamu belum join channel",
            show_alert=True
        )

    # =========================
    # SUCCESS
    # =========================
    await call.message.edit_text("✅ VERIFIED")

    await call.message.answer(
        "🔥 ACCESS GRANTED\n\n"
        "😏 Silakan lanjut pakai bot.",
        reply_markup=get_keyboard()
    )

    await call.answer()
# =========================
# UP FILE INIT
# =========================

def upload_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ DONE",
                    callback_data="upload_done"
                ),
                InlineKeyboardButton(
                    text="❌ CANCEL",
                    callback_data="upload_cancel"
                )
            ]
        ]
    )

@router.message(F.text == "📤 Up File")
async def up_file(message: Message):

    user_id = message.from_user.id

    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)

    user_states[user_id] = {"mode": "upload"}

    upload_sessions[user_id] = {
        "video": 0,
        "photo": 0,
        "document": 0,
        "items": [],
        "msg_id": None
    }

    msg = await message.answer(
        "📤 UPLOAD MODE AKTIF\n\n"
        "😏 Silakan kirim file kamu.\n"
        "Tapi jangan lupa tekan DONE ya...\n\n"
        "💀 Bot nggak akan menunggu kamu selamanya.",
        reply_markup=upload_kb()
    )

    upload_sessions[user_id]["msg_id"] = msg.message_id
# =========================
# MEDIA HANDLER
# =========================

@router.message(F.photo | F.video | F.document)
async def handle_media(message: Message):

    user_id = message.from_user.id

    state = user_states.get(user_id)
    s = upload_sessions.get(user_id)

    # ❌ bukan upload mode
    if not state or state.get("mode") != "upload":
        return

    # ❌ session invalid
    if not s or not s.get("msg_id"):
        return

    # =========================
    # GET FILE DATA
    # =========================
    if message.photo:
        file_obj = message.photo[-1]
        file_type = "photo"
        s["photo"] = s.get("photo", 0) + 1

    elif message.video:
        file_obj = message.video
        file_type = "video"
        s["video"] = s.get("video", 0) + 1

    elif message.document:
        file_obj = message.document
        file_type = "document"
        s["document"] = s.get("document", 0) + 1

    else:
        return

    file_id = file_obj.file_id
    size = getattr(file_obj, "file_size", 0) or 0

    # =========================
    # SAVE TEMP SESSION
    # =========================
    s["items"].append({
        "file_id": file_id,
        "type": file_type,
        "size": size
    })

    # =========================
    # DELETE USER MESSAGE (ANTI SPAM CLEAN)
    # =========================
    try:
        await message.delete()
    except:
        pass

    # =========================
    # THROTTLE EDIT (ANTI FLOOD UI)
    # =========================
    now = time.time()
    if now - last_edit_time.get(user_id, 0) < 0.9:
        return
    last_edit_time[user_id] = now

    # =========================
    # STATS
    # =========================
    total = len(s["items"])
    size_mb = round(
        sum(x["size"] for x in s["items"]) / (1024 * 1024),
        2
    )

    text = (
        "📤 UPLOADING...\n\n"
        f"🎥 Video     : {s.get('video', 0)}\n"
        f"🖼 Photo     : {s.get('photo', 0)}\n"
        f"📁 Document  : {s.get('document', 0)}\n"
        f"📦 Total     : {total}\n"
        f"💾 Size      : {size_mb} MB\n"
    )

    # =========================
    # UPDATE MESSAGE
    # =========================
    try:
        await message.bot.edit_message_text(
            chat_id=user_id,
            message_id=s["msg_id"],
            text=text,
            reply_markup=upload_kb()
        )
    except TelegramBadRequest:
        pass
# =========================
# GENERATE CODE
# =========================

def generate_code(v, p, d):

    import hashlib

    base = f"{v}{p}{d}{secrets.token_hex(4)}"

    rand = hashlib.sha1(base.encode()).hexdigest()[:12]

    return f"tzy_{v}v_{p}p_{d}d_{rand}"

# =========================
# DONE
# =========================

@router.callback_query(F.data == "upload_done")
async def done(call: CallbackQuery):

    user_id = call.from_user.id
    s = upload_sessions.get(user_id)

    if not s or not s.get("items"):
        return await call.answer(
            "😏 kosong? ya jelas gak ada yang diproses",
            show_alert=True
        )

    code = generate_code(
        s.get("video", 0),
        s.get("photo", 0),
        s.get("document", 0)
    )

    total_items = len(s["items"])
    total_size = sum(x.get("size", 0) for x in s["items"])

    saved_items = []

    async with db_pool.acquire() as conn:

        # =========================
        # SAVE CODE META
        # =========================
        await conn.execute(
            """
            INSERT INTO codes(code, owner_id, total_media, total_size)
            VALUES($1,$2,$3,$4)
            """,
            code,
            user_id,
            total_items,
            total_size
        )

        # =========================
        # UPLOAD TO CHANNEL (HYBRID STORAGE)
        # =========================
        for m in s["items"]:

            file_type = m.get("type")
            file_id = m.get("file_id")

            if file_type == "photo":
                msg = await call.bot.send_photo(
                    chat_id=CHANNEL_DB,
                    photo=file_id
                )
                new_file_id = msg.photo[-1].file_id

            elif file_type == "video":
                msg = await call.bot.send_video(
                    chat_id=CHANNEL_DB,
                    video=file_id
                )
                new_file_id = msg.video.file_id

            else:
                msg = await call.bot.send_document(
                    chat_id=CHANNEL_DB,
                    document=file_id
                )
                new_file_id = msg.document.file_id

            saved_items.append(
                (code, new_file_id, file_type, m.get("size", 0))
            )

        # =========================
        # SAVE MEDIA INDEX
        # =========================
        await conn.executemany(
            """
            INSERT INTO medias(code, file_id, file_type, file_size)
            VALUES($1,$2,$3,$4)
            """,
            saved_items
        )

    # =========================
    # CLEANUP SESSION
    # =========================
    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)
    last_edit_time.pop(user_id, None)

    # =========================
    # RESPONSE MESSAGE
    # =========================
    await call.message.edit_text(
        "💀 UPLOAD COMPLETE\n\n"
        f"😏 CODE: <code>{code}</code>\n\n"
        f"📦 Total File : {total_items}\n"
        f"💾 Size      : {round(total_size / (1024 * 1024), 2)} MB\n\n"
        "📦 File sudah tersimpan Di Hati😍\n"
        "🤖 Bot: tzyfilerobot",
        parse_mode="HTML"
    )
# =========================
# CANCEL
# =========================

@router.callback_query(
    F.data == "upload_cancel"
)
async def cancel(
    call: CallbackQuery
):

    user_id = call.from_user.id

    upload_sessions.pop(
        user_id,
        None
    )

    user_states.pop(
        user_id,
        None
    )

    await call.message.edit_text(
        "❌ Cancelled"
    )
# =========================
# OPEN GET FILE MODE
# =========================

@router.message(F.text == "📥 Get File")
async def get_file_start(message: Message):

    user_id = message.from_user.id

    user_states[user_id] = {
        "mode": "getfile"
    }

    await message.answer(
        "📥 Kirim CODE untuk ambil file kamu\n\n"
        "⚡ Cepetan Cok..."
    )
# =========================
# LOAD DATA FROM DB
# =========================

async def load_media(code: str):

    async with db_pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT file_id, file_type, file_size
            FROM medias
            WHERE code=$1
            ORDER BY id ASC
            """,
            code
        )
# =========================
# GETFILE
# =========================

@router.message(F.text & ~F.text.startswith("/"))
async def receive_code(message: Message):

    user_id = message.from_user.id
    text = message.text.strip()

    state = user_states.get(user_id)

    if not state or state.get("mode") != "getfile":
        return

    data = await load_media(text)

    if not data:
        return await message.answer("❌ CODE tidak ditemukan atau salah")

    user_states[user_id] = {
        "mode": "view",
        "code": text,
        "page": 0,
        "data": data
    }

    await render_first_page(message, user_id)

async def render_first_page(message: Message, user_id: int):

    state = user_states[user_id]
    data = state["data"]

    page = 0
    page_size = 5

    start = 0
    chunk = data[:page_size]

    total_pages = (len(data) + page_size - 1) // page_size
    total_media = len(data)

    text = (
        f"📦 CODE: {state['code']}\n"
        f"📄 Page: 1/{total_pages}\n"
        f"📁 Media: 1-{len(chunk)} / {total_media}\n"
        f"🔒 Powered By TZY FILE BOT"
    )

    await message.answer(
        text,
        reply_markup=build_kb(user_id, page, total_pages)
    )
# =========================
# BUILD KEYBOARD
# =========================

def build_kb(user_id, page, total_pages, show_numbers=True):

    nav = []

    now = time.time()

    history = page_history.get(user_id, {})

    nav.append(
        InlineKeyboardButton(text="⬅ Prev", callback_data="prev")
    )

    if show_numbers:

        for i in range(total_pages):

            if i == page:
                emoji = "✅"  # current page
            elif i in history:
                emoji = "☑️"  # already opened
            else:
                emoji = "❎"  # not opened yet

            nav.append(
                InlineKeyboardButton(
                    text=f"{i+1}{emoji}",
                    callback_data=f"page:{i}"
                )
            )

    nav.append(
        InlineKeyboardButton(text="Next ➡", callback_data="next")
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            nav,
            [
                InlineKeyboardButton(
                    text="📢 JOIN CHANNEL",
                    url="https://t.me/+slzhVF3Lev0zZTRh"
                ),
                InlineKeyboardButton(
                    text="💬 GROUP CHAT",
                    url="https://t.me/gcbotkx"
                )
            ]
        ]
    )

@router.callback_query(F.data == "next")
async def next_page(call: CallbackQuery):

    user_id = call.from_user.id
    state = user_states.get(user_id)

    if not state:
        return await call.answer("Session expired")

    max_page = (len(state["data"]) - 1) // 5

    if state["page"] < max_page:
        page_history.setdefault(user_id, set()).add(state["page"])
        state["page"] += 1

    await call.answer()
    await render_page(call, user_id)


@router.callback_query(F.data == "prev")
async def prev_page(call: CallbackQuery):

    user_id = call.from_user.id
    state = user_states.get(user_id)

    if not state:
        return await call.answer("Session expired")

    if state["page"] > 0:
        page_history.setdefault(user_id, set()).add(state["page"])
        state["page"] -= 1

    await call.answer()
    await render_page(call, user_id)

@router.callback_query(F.data.startswith("page:"))
async def goto_page(call: CallbackQuery):

    user_id = call.from_user.id
    state = user_states.get(user_id)

    if not state:
        return await call.answer("Session expired")

    page = int(call.data.split(":")[1])

    page_history.setdefault(user_id, set()).add(state["page"])
    state["page"] = page

    await call.answer()
    await render_page(call, user_id)
    
# =========================
# SEND PAGE
# =========================

async def render_page(call: CallbackQuery, user_id: int):

    state = user_states.get(user_id)
    if not state:
        return await call.message.answer("❌ Session expired, kirim CODE lagi")

    data = state["data"]
    page_size = 5
    page = state["page"]

    start = page * page_size
    chunk = data[start:start + page_size]

    total_pages = (len(data) + page_size - 1) // page_size
    total_media = len(data)

    size_mb = round(sum(x["file_size"] for x in data) / (1024 * 1024), 2)

    text = (
        f"📦 CODE: {state['code']}\n"
        f"📄 Page: {page+1}/{total_pages}\n"
        f"📁 Media: {start+1}-{start+len(chunk)} / {total_media}\n"
        f"💾 Size: {size_mb} MB\n"
        f"🔒 Powered By TZY FILE BOT"
    )

    # 🔥 DELETE OLD MEDIA (ANTI SPAM CHAT)
    try:
        await call.message.delete()
    except:
        pass

    # SEND MEDIA
    try:
        media_group = []

        for media in chunk:
            if media["file_type"] == "photo":
                media_group.append(InputMediaPhoto(media=media["file_id"]))
            elif media["file_type"] == "video":
                media_group.append(InputMediaVideo(media=media["file_id"]))
            else:
                media_group.append(InputMediaDocument(media=media["file_id"]))

        if media_group:
            await call.message.answer_media_group(media_group)

    except:
        pass

    await call.message.answer(
        text,
        reply_markup=build_kb(user_id, page, total_pages)
    )
# =========================
# ADD USER FUNCTION
# =========================

async def add_user(
    user_id,
    username,
    fullname
):

    async with db_pool.acquire() as conn:

        await conn.execute(
            """
            INSERT INTO users
            (user_id,username,fullname)

            VALUES($1,$2,$3)

            ON CONFLICT(user_id)

            DO UPDATE SET

            username=$2,
            fullname=$3
            """,

            user_id,
            username,
            fullname
        )

# =========================
# ACCOUNT
# =========================

@router.message(F.text == "/account")
async def account_cmd(message: Message):

    user = message.from_user

    # simpan user kalau belum ada
    await add_user(
        user.id,
        user.username or "none",
        user.full_name
    )

    async with db_pool.acquire() as conn:

        # ambil semua code milik user
        codes = await conn.fetch(
            """
            SELECT code, total_media, total_size
            FROM codes
            WHERE owner_id = $1
            ORDER BY id DESC
            LIMIT 10
            """,
            user.id
        )

        total_codes = await conn.fetchval(
            "SELECT COUNT(*) FROM codes WHERE owner_id = $1",
            user.id
        )

    # =========================
    # FORMAT LIST CODE
    # =========================
    if codes:
        code_text = "\n".join(
            f"📦 {c['code']} | {c['total_media']} file"
            for c in codes
        )
    else:
        code_text = "❌ Belum punya code"

    await message.answer(
        f"👤 ACCOUNT INFO\n\n"
        f"🆔 ID: {user.id}\n"
        f"👤 Name: {user.full_name}\n"
        f"🔗 Username: @{user.username or 'none'}\n\n"
        f"📊 TOTAL CODE: {total_codes}\n\n"
        f"📁 LAST CODE:\n{code_text}"
    )
# =========================
# VIP
# =========================

def vip_kb():

    link = (
        VIP_LINK
        .replace("https://t.me/", "")
        .replace("@", "")
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 JOIN VIP CHANNEL",
                    url=f"https://t.me/{link}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data="vip_cancel"
                )
            ]
        ]
    )


@router.message(F.text == "/vip")
async def vip_cmd(message: Message):

    await message.answer(
        "💎 VIP ACCESS ACTIVATED (DEMO MODE)\n\n"
        "━━━━━━━━━━━━━━\n"
        "🔥 BENEFIT VIP\n"
        "━━━━━━━━━━━━━━\n\n"
        "⚡ Unlimited Upload File\n"
        "⚡ Priority Processing (No Queue)\n"
        "⚡ Fast Get File Access\n"
        "⚡ Anti Limit System\n"
        "⚡ Full Media Support (Photo / Video / Document)\n\n"
        "━━━━━━━━━━━━━━\n"
        "📦 STORAGE INFO\n"
        "━━━━━━━━━━━━━━\n"
        "📁 Media disimpan full di channel database\n"
        "🔒 Aman (hanya bisa diakses via CODE)\n"
        "⚠ Tapi jangan harap gratisan diperlakukan spesial 😏\n\n"
        "━━━━━━━━━━━━━━\n"
        "💀 SAVAGE NOTICE\n"
        "━━━━━━━━━━━━━━\n"
        "• VIP bukan buat orang yang cuma nanya doang\n"
        "• Bot gak peduli kamu buru-buru\n"
        "• Semua tetap pakai sistem CODE\n"
        "• Salah pakai? ya itu masalah kamu sendiri 😌\n",
        reply_markup=vip_kb()
    )

@router.callback_query(F.data == "vip_cancel")
async def vip_cancel(call: CallbackQuery):

    await call.message.edit_text(
        "❌ VIP ACCESS CLOSED\n\n"
        "😏 Ya udah, balik ke mode gratisan lagi.\n"
        "Kalau masih mau VIP, jangan cuma klik—tapi bayar juga."
    )
# =========================
# ADMIN CHECK
# =========================

def is_admin(
    user_id: int
):

    return user_id in ADMINS

# =========================
# ADD ADMIN
# =========================

@router.message(F.text.startswith("/addadmin"))
async def add_admin(message: Message):

    # =========================
    # SECURITY CHECK
    # =========================
    if not is_admin(message.from_user.id):
        return await message.answer(
            "🚫 ACCESS DENIED\n\n"
            "😏 Kamu bukan admin.\n"
            "Jangan coba-coba jadi Tuhan di bot ini."
        )

    # =========================
    # PARSE ARGUMENT
    # =========================
    parts = message.text.split()

    if len(parts) != 2:
        return await message.answer(
            "❌ FORMAT SALAH\n\n"
            "Gunakan:\n"
            "/addadmin <id>"
        )

    # =========================
    # VALIDATE USER ID
    # =========================
    try:
        uid = int(parts[1])
    except ValueError:
        return await message.answer(
            "❌ INVALID ID\n\n"
            "😏 Itu bukan angka, jangan ngadi-ngadi."
        )

    # =========================
    # ADD ADMIN
    # =========================
    ADMINS.add(uid)

    await message.answer(
        "💀 ADMIN ADDED\n\n"
        f"👤 User ID: {uid}\n\n"
        "😏 Sekarang dia punya akses.\n"
        "Semoga gak disalahgunakan ya..."
    )
# =========================
# STATISTIC
# =========================

@router.message(F.text == "/stat")
async def stat_cmd(message: Message):

    # =========================
    # ADMIN CHECK
    # =========================
    if not is_admin(message.from_user.id):
        return await message.answer(
            "🚫 ACCESS DENIED\n\n"
            "😏 Kamu bukan admin.\n"
            "Stat ini bukan buat rakyat biasa."
        )

    # =========================
    # FETCH STAT SAFE
    # =========================
    try:
        async with db_pool.acquire() as conn:

            users = await conn.fetchval(
                "SELECT COUNT(*) FROM users"
            )

            codes = await conn.fetchval(
                "SELECT COUNT(*) FROM codes"
            )

            media = await conn.fetchval(
                "SELECT COUNT(*) FROM medias"
            )

    except Exception:
        return await message.answer(
            "⚠️ DATABASE ERROR\n\n"
            "😏 Server lagi ngambek, coba lagi nanti."
        )

    # =========================
    # RESPONSE
    # =========================
    await message.answer(
        "📊 SYSTEM STATISTICS\n\n"
        "━━━━━━━━━━━━━━\n"
        f"👤 Users  : {users}\n"
        f"🔑 Codes  : {codes}\n"
        f"📦 Media  : {media}\n"
        "━━━━━━━━━━━━━━\n\n"
        "💀 Bot still alive...\n"
        "😏 But everything is being watched."
    )
# =========================
# BROADCAST
# =========================

@router.message(F.text.startswith("/broadcast"))
async def broadcast_cmd(message: Message):

    # =========================
    # ADMIN CHECK
    # =========================
    if not is_admin(message.from_user.id):
        return await message.answer(
            "🚫 ACCESS DENIED\n\n"
            "😏 Kamu bukan admin.\n"
            "Broadcast itu bukan mainan anak kecil."
        )

    # =========================
    # GET MESSAGE TEXT
    # =========================
    text = message.text.replace("/broadcast", "").strip()

    if not text:
        return await message.answer(
            "❌ FORMAT SALAH\n\n"
            "Gunakan:\n"
            "/broadcast pesan"
        )

    # =========================
    # LOAD USERS
    # =========================
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch(
                "SELECT user_id FROM users"
            )
    except Exception:
        return await message.answer(
            "⚠️ DATABASE ERROR\n\n"
            "😏 Gagal ambil user list."
        )

    # =========================
    # BROADCAST LOOP
    # =========================
    sent = 0
    failed = 0

    await message.answer(
        "📡 BROADCAST STARTED...\n"
        "💀 Jangan ganggu sistem..."
    )

    for user in users:

        try:
            await message.bot.send_message(
                chat_id=user["user_id"],
                text=text
            )

            sent += 1

            # anti flood Telegram
            await asyncio.sleep(0.05)

        except Exception:
            failed += 1
            continue

    # =========================
    # RESULT
    # =========================
    await message.answer(
        "📡 BROADCAST FINISHED\n\n"
        "━━━━━━━━━━━━━━\n"
        f"📤 Sent   : {sent}\n"
        f"❌ Failed : {failed}\n"
        "━━━━━━━━━━━━━━\n\n"
        "💀 Semua user sudah kena pesan.\n"
        "😏 Tinggal tunggu reaksi dunia."
    )
# =========================
# HELP TEXT
# =========================

HELP_TEXT = """

🔥 TZY FILE BOT — HELP MENU 🔥

Selamat datang di TZY FILE BOT.
Bot ini dibuat buat upload, simpan, dan ambil file pakai CODE.

━━━━━━━━━━━━━━
📤 UP FILE
━━━━━━━━━━━━━━

1. Tekan 📤 Up File
2. Kirim foto / video / document
3. Tekan ✅ DONE
4. Bot generate CODE otomatis

Catatan:
• ❌ CANCEL = batalkan upload
• Simpan CODE sendiri
• Jangan upload lalu lupa DONE

━━━━━━━━━━━━━━
📥 GET FILE
━━━━━━━━━━━━━━

1. Tekan 📥 Get File
2. Kirim CODE
3. Bot kirim file otomatis
4. Gunakan pagination kalau file banyak

Kalau muncul:
❌ CODE tidak ditemukan

Cek:
• Salah ketik
• CODE invalid
• Salah input

━━━━━━━━━━━━━━
👤 ACCOUNT
━━━━━━━━━━━━━━

Menampilkan:

🆔 Telegram ID
👤 Nama akun
🔗 Username

━━━━━━━━━━━━━━
💎 VIP FEATURE
━━━━━━━━━━━━━━

🔥 Unlimited Upload
🔥 Faster Access
🔥 Priority Queue
🔥 Premium Support

━━━━━━━━━━━━━━
📋 RULE BOT
━━━━━━━━━━━━━━

✅ Gunakan sewajarnya
✅ Simpan CODE
✅ Ikuti aturan

❌ Spam
❌ Flood
❌ Abuse system

━━━━━━━━━━━━━━
🛠 ADMIN COMMAND
━━━━━━━━━━━━━━

/stat
→ statistik bot

/broadcast pesan
→ broadcast user

/addadmin ID
→ tambah admin

━━━━━━━━━━━━━━
⚠ COMMON ERROR
━━━━━━━━━━━━━━

CODE tidak ditemukan
→ cek code

Upload kosong
→ upload dulu

Not allowed
→ bukan admin

━━━━━━━━━━━━━━
💀 SAVAGE MODE
━━━━━━━━━━━━━━

• Bot baca command, bukan pikiran 😌
• Salah ketik bukan bug
• Simpan CODE sebelum hilang
• Tombol ada buat dipencet 😏

━━━━━━━━━━━━━━
🚀 BOT READY
━━━━━━━━━━━━━━

"""

# =========================
# HELP HANDLER
# =========================

@router.message(F.text == "/help")
async def help_cmd(message: Message):

    await message.answer(
        HELP_TEXT
    )


@router.message(F.text == "❓ Help")
async def help_button(message: Message):

    await message.answer(
        HELP_TEXT
    )
# =========================
# STARTUP
# =========================

async def main():

    bot = Bot(
        token=BOT_TOKEN
    )

    dp = Dispatcher()

    dp.include_router(
        router
    )

    await init_db()

    try:

        await dp.start_polling(
            bot
        )

    finally:

        if db_pool:

            await db_pool.close()

        await bot.session.close()


# =========================
# RUN
# =========================

if __name__ == "__main__":

    import asyncio

    asyncio.run(
        main()
    )
