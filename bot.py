# =========================
# IMPORT
# =========================

import os
import re
import time
import secrets
import asyncpg
import asyncio
import logging
from aiogram import Dispatcher

from dotenv import load_dotenv

from aiogram import Bot, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramRetryAfter,
)
# =========================
# LOGGING CONFIG
# =========================

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)
# =========================
# CONFIG
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

CHANNEL_DB = os.getenv("CHANNEL_DB")

FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL")
NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL")
VIP_LINK = os.getenv("VIP_LINK")

ADMINS = {
    int(x)
    for x in os.getenv("ADMINS", "").split(",")
    if x.strip().isdigit()
}

# =========================
# SECURITY CONFIG
# =========================

SESSION_TIMEOUT = 1800
GETFILE_COOLDOWN = 5
MAX_UPLOAD_FILES = 100
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024

# =========================
# ENV VALIDATION
# =========================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN belum diisi")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL belum diisi")

if not CHANNEL_DB:
    raise RuntimeError("CHANNEL_DB belum diisi")

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

        CREATE TABLE IF NOT EXISTS admins(
            user_id BIGINT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS codes(
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE,
            owner_id BIGINT,
            total_media INT,
            total_size BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
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
    "global": {},
    "page": {},
    "getfile": {},
}

page_history = {}
page_cooldown = {}

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
        input_field_placeholder="Upload atau ambil file..."
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

        ch = str(channel).replace("@", "").strip()

        if not ch:
            return True

        member = await bot.get_chat_member(
            f"@{ch}",
            user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except TelegramBadRequest:
        return False

    except Exception as e:
        print("force_sub error:", e)
        return False


def force_kb(channel):

    ch = str(channel).replace("@", "").strip()

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
# UP FILE INIT (FIXED)
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

    user_states[user_id] = {
        "mode": "upload",
        "last_activity": time.time()
    }

    upload_sessions[user_id] = {
        "video": 0,
        "photo": 0,
        "document": 0,
        "items": [],
        "total_size": 0,   # 🔥 FIX: incremental size
        "msg_id": None,
        "chat_id": message.chat.id
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
# MEDIA HANDLER (FIXED)
# =========================

@router.message(F.photo | F.video | F.document)
async def handle_media(message: Message):

    user_id = message.from_user.id

    state = user_states.get(user_id)
    session = upload_sessions.get(user_id)

    # =========================
    # VALIDATION MODE
    # =========================
    if not state or state.get("mode") != "upload":
        return

    if not session or not session.get("msg_id"):
        return

    # =========================
    # GET FILE DATA
    # =========================
    file_obj = None
    file_type = None

    if message.photo:
        file_obj = message.photo[-1]
        file_type = "photo"
        session["photo"] = session.get("photo", 0) + 1

    elif message.video:
        file_obj = message.video
        file_type = "video"
        session["video"] = session.get("video", 0) + 1

    elif message.document:
        file_obj = message.document
        file_type = "document"
        session["document"] = session.get("document", 0) + 1

    if not file_obj:
        return

    file_id = file_obj.file_id
    size = getattr(file_obj, "file_size", 0) or 0

    # =========================
    # LIMIT FILE COUNT
    # =========================
    if len(session.get("items", [])) >= MAX_UPLOAD_FILES:
        return await message.answer(
            f"❌ Maksimal {MAX_UPLOAD_FILES} file per upload."
        )

    # =========================
    # LIMIT SIZE (SAFE)
    # =========================
    current_size = session.get("total_size", 0)

    if current_size + size > MAX_UPLOAD_SIZE:
        return await message.answer(
            "❌ Total upload melebihi batas ukuran."
        )

    # =========================
    # SAVE SESSION
    # =========================
    session.setdefault("items", []).append({
        "file_id": file_id,
        "type": file_type,
        "size": size
    })

    session["total_size"] = current_size + size

    # =========================
    # DELETE USER MESSAGE (SAFE)
    # =========================
    try:
        await message.delete()
    except Exception:
        pass

    # =========================
    # THROTTLE EDIT (ANTI SPAM SAFE)
    # =========================
    now = time.time()

    last_time = last_edit_time.get(user_id, 0)

    if now - last_time < 0.5:
        return

    last_edit_time[user_id] = now

    # =========================
    # STATS
    # =========================
    total = len(session["items"])

    size_mb = round(session["total_size"] / (1024 * 1024), 2)

    text = (
        "📤 UPLOADING...\n\n"
        f"🎥 Video     : {session.get('video', 0)}\n"
        f"🖼 Photo     : {session.get('photo', 0)}\n"
        f"📁 Document  : {session.get('document', 0)}\n"
        f"📦 Total     : {total}\n"
        f"💾 Size      : {size_mb} MB"
    )

    # =========================
    # EDIT MESSAGE (SAFE + RETRY)
    # =========================
    try:
        await message.bot.edit_message_text(
            chat_id=session["chat_id"],
            message_id=session["msg_id"],
            text=text,
            reply_markup=upload_kb()
        )

    except TelegramBadRequest:
        pass

    except Exception:
        pass
# =========================
# GENERATE CODE (OK)
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

    session = upload_sessions.get(user_id)

    if not session or not session.get("items"):

        return await call.answer(
            "😏 kosong? ya jelas gak ada yang diproses",
            show_alert=True
        )

    code = generate_code(
        session.get("video", 0),
        session.get("photo", 0),
        session.get("document", 0)
    )

    total_items = len(session["items"])

    total_size = sum(
        x.get("size", 0)
        for x in session["items"]
    )

    saved_items = []

    async with db_pool.acquire() as conn:

        await conn.execute(
            """
            INSERT INTO codes
            (
                code,
                owner_id,
                total_media,
                total_size
            )
            VALUES($1,$2,$3,$4)
            """,
            code,
            user_id,
            total_items,
            total_size
        )

        for item in session["items"]:

            file_type = item["type"]
            file_id = item["file_id"]

            try:

                if file_type == "photo":

                    msg = await call.bot.send_photo(
                        CHANNEL_DB,
                        photo=file_id
                    )

                    new_file_id = msg.photo[-1].file_id

                elif file_type == "video":

                    msg = await call.bot.send_video(
                        CHANNEL_DB,
                        video=file_id
                    )

                    new_file_id = msg.video.file_id

                else:

                    msg = await call.bot.send_document(
                        CHANNEL_DB,
                        document=file_id
                    )

                    new_file_id = msg.document.file_id

            except TelegramRetryAfter as e:

                await asyncio.sleep(e.retry_after)

                continue

            saved_items.append(
                (
                    code,
                    new_file_id,
                    file_type,
                    item.get("size", 0)
                )
            )

        if saved_items:

            await conn.executemany(
                """
                INSERT INTO medias
                (
                    code,
                    file_id,
                    file_type,
                    file_size
                )
                VALUES($1,$2,$3,$4)
                """,
                saved_items
            )

    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)
    last_edit_time.pop(user_id, None)

    await call.message.edit_text(
        "💀 UPLOAD COMPLETE\n\n"
        f"😏 CODE: <code>{code}</code>\n\n"
        f"📦 Total File : {total_items}\n"
        f"💾 Size : {round(total_size / (1024 * 1024), 2)} MB\n\n"
        "📦 File berhasil disimpan.\n"
        "🤖 Bot: tzyfilerobot",
        parse_mode="HTML"
    )


# =========================
# CANCEL
# =========================

@router.callback_query(F.data == "upload_cancel")
async def cancel(call: CallbackQuery):

    user_id = call.from_user.id

    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)
    last_edit_time.pop(user_id, None)

    await call.message.edit_text(
        "❌ Upload dibatalkan."
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
# NORMALIZER
# =========================

def normalize_type(t):

    t = (t or "").lower().strip()

    if t in ["photo", "image", "img"]:
        return "photo"

    if t in ["video", "vid"]:
        return "video"

    if t in ["doc", "document", "file"]:
        return "document"

    return "document"


# =========================
# LOAD MEDIA
# =========================

async def load_media(code: str):

    if not code:
        return []

    async with db_pool.acquire() as conn:

        rows = await conn.fetch(
            """
            SELECT
                file_id,
                file_type,
                COALESCE(file_size,0) AS file_size
            FROM medias
            WHERE code=$1
            ORDER BY id ASC
            """,
            code
        )

    return [
        {
            "file_id": row["file_id"],
            "file_type": normalize_type(row["file_type"]),
            "file_size": row["file_size"]
        }
        for row in rows
    ]


# =========================
# SEND MEDIA GROUP
# =========================

async def send_media(
    bot,
    chat_id: int,
    chunk: list
):

    if not chunk:
        return

    media_group = []

    for item in chunk[:5]:

        file_type = (
            item.get("file_type") or ""
        ).lower().strip()

        file_id = item.get("file_id")

        if not file_id:
            continue

        if file_type == "photo":

            media_group.append(
                InputMediaPhoto(
                    media=file_id
                )
            )

        elif file_type == "video":

            media_group.append(
                InputMediaVideo(
                    media=file_id
                )
            )

        else:

            media_group.append(
                InputMediaDocument(
                    media=file_id
                )
            )

    if not media_group:
        return

    await bot.send_media_group(
        chat_id=chat_id,
        media=media_group
    )


# =========================
# GET FILE HANDLER
# =========================

@router.message(
    F.text &
    ~F.text.startswith("/")
)
async def receive_code(
    message: Message
):

    user_id = message.from_user.id
    text = (message.text or "").strip()

    state = user_states.get(user_id)

    if not state:
        return

    if state.get("mode") != "getfile":
        return

    if not text:
        return

    # =========================
    # MULTI CODE EXTRACTION
    # =========================

    codes = re.findall(
        r"CODE\s*[:=]?\s*([A-Za-z0-9_]{6,})",
        text,
        re.IGNORECASE
    )

    # user paste code langsung
    if not codes:

        codes = re.findall(
            r"\b([A-Za-z0-9_]{10,})\b",
            text
        )

    # chinese variation
    if not codes:

        codes = re.findall(
            r"(?:代码|CODE)\s*[:=]?\s*([A-Za-z0-9_]{6,})",
            text,
            re.IGNORECASE
        )

    # =========================
    # VALIDATION
    # =========================

    codes = list(
        dict.fromkeys(codes)
    )

    if not codes:

        return await message.answer(
            "❌ CODE tidak ditemukan"
        )

    # anti spam
    codes = codes[:10]

    all_data = []

    # =========================
    # LOAD ALL CODES
    # =========================

    for code in codes:

        code = code.strip()

        if len(code) < 6:
            continue

        try:

            data = await load_media(code)

            if data:
                all_data.extend(data)

        except Exception as e:

            print(
                f"LOAD ERROR {code}:",
                e
            )

    if not all_data:

        return await message.answer(
            "❌ Semua CODE tidak valid"
        )

    # =========================
    # SET STATE
    # =========================

    user_states[user_id] = {
        "mode": "view",
        "code": codes[0],
        "page": 0,
        "data": all_data
    }

    page_history[user_id] = set()

    # =========================
    # RENDER UI
    # =========================

    try:

        await render_first_page(
            message,
            user_id
        )

    except Exception as e:

        print(
            "RENDER ERROR:",
            e
        )

        await message.answer(
            "❌ Error saat menampilkan file"
        )
        
# =========================
# KB BUILDER
# =========================

def build_kb(
    user_id,
    page,
    total_pages
):

    history = page_history.get(
        user_id,
        set()
    )

    buttons = []

    # =========================
    # NAVIGATION
    # =========================

    buttons.append([
        InlineKeyboardButton(
            text="⬅ Prev",
            callback_data="prev"
        ),
        InlineKeyboardButton(
            text="➡ Next",
            callback_data="next"
        )
    ])

    # =========================
    # PAGE WINDOW
    # =========================

    page_row = []

    window = 5

    start = max(
        0,
        page - 2
    )

    end = start + window

    if end > total_pages:
        end = total_pages
        start = max(
            0,
            end - window
        )

    for i in range(start, end):

        if i == page:
            emoji = "🟢"

        elif i in history:
            emoji = "🟡"

        else:
            emoji = "⚪"

        page_row.append(
            InlineKeyboardButton(
                text=f"{i+1}{emoji}",
                callback_data=f"page:{i}"
            )
        )

    if page_row:
        buttons.append(page_row)

    # =========================
    # FOOTER
    # =========================

    buttons.append([
        InlineKeyboardButton(
            text="📢 JOIN CHANNEL",
            url="https://t.me/+slzhVF3Lev0zZTRh"
        ),
        InlineKeyboardButton(
            text="💬 GROUP CHAT",
            url="https://t.me/gcbotkx"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


# =========================
# RENDER FIRST PAGE
# =========================

async def render_first_page(
    message,
    user_id: int
):

    state = user_states.get(user_id)

    if not state:
        return await message.answer(
            "Session expired"
        )

    data = state.get("data", [])

    if not data:
        return await message.answer(
            "❌ Tidak ada media"
        )

    state["page"] = 0

    page_size = 5
    page = 0

    start = page * page_size

    chunk = data[
        start:
        start + page_size
    ]

    total_pages = max(
        1,
        (len(data) + page_size - 1)
        // page_size
    )

    page_history[user_id] = {0}

    await send_media(
        message.bot,
        message.chat.id,
        chunk
    )

    text = (
        f"📦 CODE: {state['code']}\n"
        f"📄 Page: {page+1}/{total_pages}\n"
        f"📁 Media: {start+1}-{start+len(chunk)} / {len(data)}"
    )

    kb = build_kb(
        user_id,
        page,
        total_pages
    )

    msg = await message.answer(
        text,
        reply_markup=kb
    )

    state["msg_id"] = msg.message_id


# =========================
# RENDER PAGE
# =========================

async def render_page(
    call,
    user_id: int
):

    state = user_states.get(user_id)

    if not state:
        return await call.answer(
            "Session expired"
        )

    data = state.get("data", [])

    if not data:
        return await call.answer(
            "No data"
        )

    page_size = 5

    max_page = (
        len(data) - 1
    ) // page_size

    page = max(
        0,
        min(
            state.get("page", 0),
            max_page
        )
    )

    state["page"] = page

    start = page * page_size

    chunk = data[
        start:
        start + page_size
    ]

    total_pages = max(
        1,
        (len(data) + page_size - 1)
        // page_size
    )

    await send_media(
        call.bot,
        call.message.chat.id,
        chunk
    )

    text = (
        f"📦 CODE: {state['code']}\n"
        f"📄 Page: {page+1}/{total_pages}\n"
        f"📁 Media: {start+1}-{start+len(chunk)} / {len(data)}"
    )

    kb = build_kb(
        user_id,
        page,
        total_pages
    )

    try:

        await call.message.edit_text(
            text,
            reply_markup=kb
        )

    except TelegramBadRequest:
        pass

    await call.answer()


# =========================
# NEXT
# =========================

@router.callback_query(
    F.data == "next"
)
async def next_page(call):

    user_id = call.from_user.id

    if user_click_lock.get(user_id):
        return await call.answer()

    user_click_lock[user_id] = True

    try:

        state = user_states.get(user_id)

        if not state:
            return await call.answer(
                "Session expired"
            )

        data = state.get("data", [])

        if not data:
            return await call.answer(
                "No data"
            )

        page_size = 5

        max_page = (
            len(data) - 1
        ) // page_size

        if state["page"] >= max_page:
            return await call.answer(
                "Last page"
            )

        state["page"] += 1

        page_history.setdefault(
            user_id,
            set()
        ).add(
            state["page"]
        )

        await render_page(
            call,
            user_id
        )

    finally:

        user_click_lock.pop(
            user_id,
            None
        )


# =========================
# PREV
# =========================

@router.callback_query(
    F.data == "prev"
)
async def prev_page(call):

    user_id = call.from_user.id

    if user_click_lock.get(user_id):
        return await call.answer()

    user_click_lock[user_id] = True

    try:

        state = user_states.get(user_id)

        if not state:
            return await call.answer(
                "Session expired"
            )

        if state.get("page", 0) <= 0:
            return await call.answer(
                "First page"
            )

        state["page"] -= 1

        page_history.setdefault(
            user_id,
            set()
        ).add(
            state["page"]
        )

        await render_page(
            call,
            user_id
        )

    finally:

        user_click_lock.pop(
            user_id,
            None
        )


# =========================
# GOTO PAGE
# =========================

@router.callback_query(
    F.data.startswith("page:")
)
async def goto_page(call):

    user_id = call.from_user.id

    if user_click_lock.get(user_id):
        return await call.answer()

    user_click_lock[user_id] = True

    try:

        state = user_states.get(user_id)

        if not state:
            return await call.answer(
                "Session expired"
            )

        data = state.get("data", [])

        if not data:
            return await call.answer(
                "No data"
            )

        try:

            page = int(
                call.data.split(":")[1]
            )

        except (
            ValueError,
            IndexError
        ):
            return await call.answer(
                "Invalid page"
            )

        page_size = 5

        max_page = (
            len(data) - 1
        ) // page_size

        page = max(
            0,
            min(page, max_page)
        )

        state["page"] = page

        page_history.setdefault(
            user_id,
            set()
        ).add(page)

        await render_page(
            call,
            user_id
        )

    finally:

        user_click_lock.pop(
            user_id,
            None
        )
# ======================
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
            ORDER BY code DESC
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
    # PARSE MESSAGE
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
            users = await conn.fetch("SELECT user_id FROM users")
    except Exception:
        return await message.answer(
            "⚠️ DATABASE ERROR\n\n"
            "😏 Gagal ambil user list."
        )

    total = len(users)
    sent = 0
    failed = 0

    await message.answer(
        f"📡 BROADCAST STARTED...\n"
        f"👥 Target: {total}\n"
        "💀 Sistem mulai bekerja..."
    )

    # =========================
    # BROADCAST LOOP (SAFE MODE)
    # =========================
    for i, user in enumerate(users, start=1):

        try:
            await message.bot.send_message(
                chat_id=user["user_id"],
                text=text
            )

            sent += 1

        except Exception:
            failed += 1

        # =========================
        # ANTI FLOOD CONTROL
        # =========================
        if i % 20 == 0:
            await asyncio.sleep(0.5)

        else:
            await asyncio.sleep(0.03)

    # =========================
    # RESULT
    # =========================
    await message.answer(
        "📡 BROADCAST FINISHED\n\n"
        "━━━━━━━━━━━━━━\n"
        f"👥 Total  : {total}\n"
        f"📤 Sent   : {sent}\n"
        f"❌ Failed : {failed}\n"
        "━━━━━━━━━━━━━━\n\n"
        "💀 Done sending to all users."
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
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(router)

    try:
        # init database dulu
        await init_db()

        # start bot
        await dp.start_polling(bot)

    except Exception as e:
        print("BOT ERROR:", e)

    finally:
        # cleanup aman
        global db_pool

        if db_pool is not None:
            await db_pool.close()
            db_pool = None

        await bot.session.close()


# =========================
# RUN
# =========================

if __name__ == "__main__":

    import asyncio

    asyncio.run(
        main()
    )
