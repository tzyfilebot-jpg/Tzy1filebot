# =========================
# IMPORT
# =========================

import os
import re
import secrets
import string
import asyncpg
import time
import asyncio
import random

from dotenv import load_dotenv
from aiogram.filters import CommandStart
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

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

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

FORCE_CHANNEL = int(os.getenv("FORCE_CHANNEL"))
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL")
NOTIFICATION_CHANNEL = int(os.getenv("NOTIFICATION_CHANNEL"))
VIP_LINK = os.getenv("VIP_LINK")

# =========================
# DB POOL (OPTIMIZED)
# =========================

db_pool: asyncpg.Pool | None = None

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,

        # =========================
        # POOL SETTINGS
        # =========================
        min_size=2,
        max_size=5,

        # =========================
        # PGBOUNCER FIX (WAJIB)
        # =========================
        statement_cache_size=0,

        # =========================
        # TIMEOUT
        # =========================
        command_timeout=15
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
# CACHE / MEMORY
# =========================

cooldown = {
    "global": {},
    "page": {},
}

page_history = {}
page_cooldown = {}
user_click_lock = {}
upload_sessions = {}
user_states = {}
last_edit_time = {}
user_last_action = {}
force_cache = {}

# key = (user_id, channel)
# value = (status, expire_time)

# =========================
# ANTI BANNED SYSTEM 🔥
# =========================

GLOBAL_DELAY = 0.08
last_global_send = 0

USER_DELAY = 1.5

def user_limit(user_id):
    now = time.time()
    last = user_last_action.get(user_id, 0)

    if now - last < USER_DELAY:
        return False

    user_last_action[user_id] = now
    return True

async def global_throttle():
    global last_global_send

    now = time.time()
    diff = now - last_global_send

    if diff < GLOBAL_DELAY:
        await asyncio.sleep(GLOBAL_DELAY - diff)

    last_global_send = time.time()

async def safe_send(func, *args, **kwargs):
    for _ in range(5):
        try:
            await global_throttle()
            return await func(*args, **kwargs)

        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)

        except TelegramBadRequest as e:
            print("BAD REQUEST:", e)
            return

        except Exception as e:
            print("ERROR:", e)
            await asyncio.sleep(1)


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
        input_field_placeholder="Upload atau ambil file... 😏"
    )

# =========================
# CONFIG FORCE SUB
# =========================

# PRIVATE CHANNEL
FORCE_CHANNEL = -1003712587847
FORCE_CHANNEL_LINK = "https://t.me/+3g_yhHwxCrc5ZTg9"

# PUBLIC CHANNEL
# FORCE_CHANNEL = "@mychannel"
# FORCE_CHANNEL_LINK = "https://t.me/mychannel"


# =========================
# CHECK FORCE SUB
# =========================

async def check_force_sub(bot: Bot, user_id: int, channel):
    try:
        member = await bot.get_chat_member(
            chat_id=channel,
            user_id=user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception as e:
        print("FORCE SUB ERROR:", e)
        return False


# =========================
# FORCE SUB KEYBOARD
# =========================

def force_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Join Channel",
                    url=FORCE_CHANNEL_LINK
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Sudah Join",
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

    # SAVE USER
    try:
        await add_user(
            user.id,
            user.username or "none",
            user.full_name
        )
    except Exception as e:
        print("ADD USER ERROR:", e)

    # ANTI SPAM
    if not user_limit(user.id):
        return await safe_send(
            message.answer,
            "⏳ Jangan spam ya 😏"
        )

    # FORCE SUB
    if FORCE_CHANNEL:

        joined = await check_force_sub(
            bot,
            user.id,
            FORCE_CHANNEL
        )

        if not joined:
            return await safe_send(
                message.answer,
                "⚠️ AKSES DITOLAK\n\n"
                "😏 Kamu belum join channel.\n"
                "Join dulu baru bisa lanjut.",
                reply_markup=force_kb()
            )

    # MENU
    await safe_send(
        message.answer,
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
        "• CODE hilang = tanggung jawab user\n"
        "• Jangan spam 😏",
        reply_markup=get_keyboard()
    )


# =========================
# CHECK SUB
# =========================

@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery, bot: Bot):

    user_id = call.from_user.id

    # ANTI SPAM
    if not user_limit(user_id):
        return await call.answer(
            "⏳ Jangan spam",
            show_alert=True
        )

    # FORCE SUB OFF
    if not FORCE_CHANNEL:
        return await call.answer(
            "Force Sub OFF",
            show_alert=True
        )

    # CHECK MEMBER
    joined = await check_force_sub(
        bot,
        user_id,
        FORCE_CHANNEL
    )

    if not joined:
        return await call.answer(
            "❌ Kamu belum join channel",
            show_alert=True
        )

    # VERIFIED
    try:
        await call.message.edit_text(
            "✅ VERIFIED\n\n"
            "Akses berhasil dibuka."
        )
    except Exception:
        pass

    await safe_send(
        call.message.answer,
        "🔥 AKSES DIBUKA\n\n"
        "😏 Silakan gunakan bot.",
        reply_markup=get_keyboard()
    )

    await call.answer(
        "Berhasil diverifikasi ✅"
    )
# =========================
# UP FILE INIT
# =========================

def upload_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ DONE", callback_data="upload_done"),
                InlineKeyboardButton(text="❌ CANCEL", callback_data="upload_cancel")
            ]
        ]
    )


@router.message(F.text == "📤 Up File")
async def up_file(message: Message):

    user_id = message.from_user.id

    # =========================
    # ANTI SPAM
    # =========================
    if not user_limit(user_id):
        return await safe_send(
            message.answer,
            "⏳ Jangan spam ya 😏"
        )

    # =========================
    # RESET SESSION LAMA
    # =========================
    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)
    last_edit_time.pop(user_id, None)

    # =========================
    # CREATE STATE
    # =========================
    user_states[user_id] = {
        "mode": "upload"
    }

    upload_sessions[user_id] = {
        "video": 0,
        "photo": 0,
        "document": 0,
        "items": [],
        "msg_id": None
    }

    # =========================
    # SEND PANEL
    # =========================
    msg = await safe_send(
        message.answer,
        "📤 UPLOAD MODE AKTIF\n\n"
        "😏 Kirim file kamu sekarang.\n"
        "Tekan DONE kalau sudah.\n\n"
        "💀 Jangan lama-lama ya...",
        reply_markup=upload_kb()
    )

    # =========================
    # VALIDASI MESSAGE
    # =========================
    if not msg:
        upload_sessions.pop(user_id, None)
        user_states.pop(user_id, None)

        return

    # =========================
    # SAVE PANEL ID
    # =========================
    upload_sessions[user_id]["msg_id"] = msg.message_id
# =========================
# MEDIA HANDLER (FINAL CLEAN)
# =========================

@router.message(F.photo | F.video | F.document)
async def handle_media(message: Message):

    user_id = message.from_user.id

    state = user_states.get(user_id)
    s = upload_sessions.get(user_id)

    # =========================
    # VALIDATION
    # =========================
    if not state or state.get("mode") != "upload":
        return

    if not s or not s.get("msg_id"):
        return

    # =========================
    # GET FILE
    # =========================
    file_obj = None
    file_type = None

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

    if not file_obj:
        return

    file_id = file_obj.file_id
    size = getattr(file_obj, "file_size", 0) or 0

    # =========================
    # SAVE TO SESSION
    # =========================
    s["items"].append({
        "file_id": file_id,
        "type": file_type,
        "size": size
    })

    # =========================
    # DELETE USER MESSAGE
    # =========================
    try:
        await message.delete()
    except:
        pass

    # =========================
    # THROTTLE (SAFE)
    # =========================
    now = time.time()
    last = last_edit_time.get(user_id, 0)

    if now - last < 1.5:
        return

    last_edit_time[user_id] = now

    # =========================
    # CALCULATE STATS
    # =========================
    total = len(s["items"])
    size_mb = round(
        sum(x.get("size", 0) for x in s["items"]) / (1024 * 1024),
        2
    )

    bar_len = 10
    filled = min(bar_len, total)
    bar = "█" * filled + "░" * (bar_len - filled)

    text = (
        "📤 UPLOAD MODE\n\n"
        f"📊 Progress : [{bar}] {total} file\n\n"
        f"🖼 Photo    : {s.get('photo', 0)}\n"
        f"🎬 Video    : {s.get('video', 0)}\n"
        f"📁 Document : {s.get('document', 0)}\n"
        f"💾 Size     : {size_mb} MB\n\n"
        "━━━━━━━━━━━━━━\n"
        "Tekan DONE kalau sudah 😏"
    )

    # =========================
    # SAFE EDIT MESSAGE
    # =========================
    try:
        await safe_send(
            message.bot.edit_message_text,
            chat_id=message.chat.id,
            message_id=s["msg_id"],
            text=text,
            reply_markup=upload_kb()
        )
    except Exception as e:
        print("EDIT ERROR:", e)
        
# =========================
# GENERATE CODE
# =========================

def generate_code(v, p, d):
    import hashlib, secrets

    base = f"{v}{p}{d}{secrets.token_hex(4)}"
    rand = hashlib.sha1(base.encode()).hexdigest()[:12]

    return f"xywukai_{v}v_{p}p_{d}d_{rand}"


@router.callback_query(F.data == "upload_done")
async def done(call: CallbackQuery):

    user_id = call.from_user.id
    s = upload_sessions.get(user_id)

    if not s or not s.get("items"):
        return await call.answer(
            "😏 kosong? ya jelas gak ada yang diproses",
            show_alert=True
        )

    # 🔥 ANTI DOUBLE CLICK / RACE CONDITION
    if s.get("processing"):
        return await call.answer("⏳ Lagi diproses...")
    s["processing"] = True

    try:
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
            # SAVE META
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
            # SAVE FILE_ID DIRECT (NO CHANNEL DB)
            # =========================
            for m in s["items"]:

                file_id = m.get("file_id")
                file_type = m.get("type")
                size = m.get("size", 0)

                if not file_id or not file_type:
                    continue

                saved_items.append(
                    (code, file_id, file_type, size)
                )

            # =========================
            # SAVE MEDIA INDEX
            # =========================
            if saved_items:
                await conn.executemany(
                    """
                    INSERT INTO medias(code, file_id, file_type, file_size)
                    VALUES($1,$2,$3,$4)
                    """,
                    saved_items
                )

        # =========================
        # FINAL RESPONSE
        # =========================
        await call.message.edit_text(
            "💀 UPLOAD COMPLETE\n\n"
            f"😏 CODE: <code>{code}</code>\n\n"
            f"📦 Total File : {total_items}\n"
            f"💾 Size      : {round(total_size / (1024 * 1024), 2)} MB\n\n"
            "📦 File berhasil disimpan 😏\n"
            "🤖 Bot: xywukaibot",
            parse_mode="HTML"
        )

    except Exception as e:
        print("DONE ERROR:", e)
        await call.message.edit_text("❌ Gagal proses upload")

    finally:
        # =========================
        # CLEAN SESSION (WAJIB AMAN)
        # =========================
        upload_sessions.pop(user_id, None)
        user_states.pop(user_id, None)
        last_edit_time.pop(user_id, None)
        
# =========================
# CANCEL HANDLER
# =========================

@router.callback_query(F.data == "upload_cancel")
async def cancel(call: CallbackQuery):

    user_id = call.from_user.id

    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)
    last_edit_time.pop(user_id, None)

    try:
        await call.message.edit_text("❌ Upload dibatalkan")
    except:
        pass
# =========================
# GLOBAL
# =========================

COOLDOWN_TIME = 5

# =========================
# NORMALIZER
# =========================
def normalize_type(t):
    t = (t or "").lower().strip()
    if t in ["photo", "image", "img"]:
        return "photo"
    if t in ["video", "vid"]:
        return "video"
    return "document"


# =========================
# COOLDOWN
# =========================
def is_cooldown(user_id):
    now = time.time()
    last = cooldown["global"].get(user_id, 0)

    if now - last < COOLDOWN_TIME:
        return True

    cooldown["global"][user_id] = now
    return False


# =========================
# LOAD MEDIA
# =========================
async def load_media(code: str):
    if not code:
        return []

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT file_id, file_type, COALESCE(file_size,0) AS file_size
                FROM medias
                WHERE code=$1
                ORDER BY id ASC
            """, code)
    except Exception as e:
        print("DB ERROR:", e)
        return []

    return [
        {
            "file_id": r["file_id"],
            "file_type": normalize_type(r["file_type"]),
            "file_size": r["file_size"]
        }
        for r in rows
    ]


# =========================
# SEND MEDIA (ANTI BAN SAFE)
# =========================
async def send_media(bot, chat_id: int, chunk: list):

    if not chunk:
        return False

    media = []

    for m in chunk[:5]:

        fid = m.get("file_id")
        ftype = (m.get("file_type") or "").lower()

        if not fid:
            continue

        try:

            if ftype == "photo":
                media.append(
                    InputMediaPhoto(media=fid)
                )

            elif ftype == "video":
                media.append(
                    InputMediaVideo(media=fid)
                )

            else:
                media.append(
                    InputMediaDocument(media=fid)
                )

        except Exception as e:
            print("MEDIA BUILD ERROR:", e)

    if not media:
        return False

    for attempt in range(5):

        try:

            await global_throttle()

            await bot.send_media_group(
                chat_id=chat_id,
                media=media
            )

            return True

        except TelegramRetryAfter as e:

            print(
                f"FLOODWAIT {e.retry_after}s"
            )

            await asyncio.sleep(
                e.retry_after + 1
            )

        except TelegramBadRequest as e:

            print(
                "BAD REQUEST:",
                e
            )

            return False

        except Exception as e:

            print(
                f"SEND MEDIA ERROR {attempt+1}:",
                e
            )

            await asyncio.sleep(
                1 + attempt
            )

    print(
        "❌ GAGAL KIRIM MEDIA"
    )

    return False
    
# =========================
# KEYBOARD
# =========================
def build_kb(user_id, page, total_pages):

    history = page_history.get(user_id, set())
    rows = []

    prev_btn = InlineKeyboardButton(
        text="⬅ Prev" if page > 0 else "⛔ Prev",
        callback_data="prev" if page > 0 else "noop"
    )

    next_btn = InlineKeyboardButton(
        text="➡ Next" if page < total_pages - 1 else "⛔ Next",
        callback_data="next" if page < total_pages - 1 else "noop"
    )

    rows.append([prev_btn, next_btn])

    # page indicator
    window = 5
    start = max(0, page - 2)
    end = min(total_pages, start + window)

    page_row = []
    for i in range(start, end):

        if i == page:
            mark = "🟢"
        elif i in history:
            mark = "🟡"
        else:
            mark = "⚪"

        page_row.append(
            InlineKeyboardButton(
                text=f"{i+1}{mark}",
                callback_data=f"page:{i}"
            )
        )

    if page_row:
        rows.append(page_row)

    # =========================
    # LINK BUTTONS (FIXED)
    # =========================
    rows.append([
        InlineKeyboardButton(
            text="📢 CHANNEL UPDATE",
            url="https://t.me/+3g_yhHwxCrc5ZTg9"
        ),
        InlineKeyboardButton(
            text="💬 GROUP CHAT",
            url="https://t.me/+1tipdp-NTywzODhl"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)
# =========================
# RENDER PAGE (FIX PANEL BAWAH)
# =========================

async def render_page(user_id: int, bot, chat_id: int):

    state = user_states.get(user_id)

    if not state:
        return

    data = state.get("data") or []

    if not data:
        return

    page = state.get("page", 0)
    size = state.get("page_size", 5)

    total_pages = max(
        1,
        (len(data) + size - 1) // size
    )

    page = max(
        0,
        min(page, total_pages - 1)
    )

    state["page"] = page

    start = page * size
    end = start + size

    chunk = data[start:end]

    # =========================
    # HISTORY
    # =========================

    page_history.setdefault(
        user_id,
        set()
    ).add(page)

    # =========================
    # SEND MEDIA
    # =========================

    try:

        await send_media(
            bot,
            chat_id,
            chunk
        )

    except Exception as e:

        print(
            "SEND MEDIA ERROR:",
            e
        )

    # =========================
    # PANEL TEXT
    # =========================

    text = (
        f"📦 CODE: <code>{state.get('code','-')}</code>\n"
        f"📄 Page: {page + 1}/{total_pages}\n"
        f"📁 Media: {start + 1}-{start + len(chunk)} / {len(data)}\n\n"
        "👇 CONTROL PANEL DI BAWAH"
    )

    kb = build_kb(
        user_id,
        page,
        total_pages
    )

    # =========================
    # DELETE PANEL LAMA
    # =========================

    panel_id = state.get("last_panel_msg")

    if panel_id:

        try:

            await safe_send(
                bot.delete_message,
                chat_id=chat_id,
                message_id=panel_id
            )

        except Exception as e:

            print(
                "DELETE PANEL ERROR:",
                e
            )

    # =========================
    # CREATE PANEL BARU
    # =========================

    try:

        msg = await safe_send(
            bot.send_message,
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )

        if msg:
            state["last_panel_msg"] = msg.message_id

    except Exception as e:

        print(
            "SEND PANEL ERROR:",
            e
        )
# =========================
# PAGINATION LOCK
# =========================
pagination_lock = {}

# =========================
# SINGLE PAGINATION HANDLER
# =========================
@router.callback_query(
    F.data.in_(["next", "prev"]) |
    F.data.startswith("page:")
)
async def pagination(call: CallbackQuery):

    user_id = call.from_user.id

    # =========================
    # ANTI DOUBLE CLICK
    # =========================
    if pagination_lock.get(user_id):
        return await call.answer()

    pagination_lock[user_id] = True

    try:

        state = user_states.get(user_id)

        if not state:
            return await call.answer(
                "Session expired",
                show_alert=True
            )

        data = state.get("data") or []

        if not data:
            return await call.answer(
                "No data",
                show_alert=True
            )

        old_page = state.get(
            "page",
            0
        )

        size = state.get(
            "page_size",
            5
        )

        max_page = (
            len(data) - 1
        ) // size

        page = old_page

        # =========================
        # PAGE CONTROL
        # =========================
        if call.data == "next":

            page += 1

        elif call.data == "prev":

            page -= 1

        else:

            try:

                page = int(
                    call.data.split(":")[1]
                )

            except Exception:

                return await call.answer(
                    "Error"
                )

        page = max(
            0,
            min(page, max_page)
        )

        # =========================
        # NO CHANGE
        # =========================
        if page == old_page:
            return await call.answer()

        state["page"] = page

        # =========================
        # RENDER PAGE
        # =========================
        await render_page(
            user_id,
            call.bot,
            call.message.chat.id
        )

        await call.answer()

    finally:

        pagination_lock.pop(
            user_id,
            None
        )

# =========================
# NOOP
# =========================
@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):

    await call.answer(
        "😏 FULL JANCOK"
    )
# =========================
# START GET FILE
# =========================
@router.message(F.text == "📥 Get File")
async def start_get(message: Message):

    user_id = message.from_user.id
    user_states[user_id] = {"mode": "getfile"}

    await message.answer("📥 Kirim CODE 😏")


# =========================
# RECEIVE CODE
# =========================
@router.message(F.text & ~F.text.startswith("/"))
async def receive_code(message: Message):

    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state or state.get("mode") != "getfile":
        return

    if is_cooldown(user_id):
        return await message.answer("⏳ Jangan spam")

    codes = re.findall(
        r"\bxywukai_[A-Za-z0-9_]+\b",
        message.text or ""
    )

    if not codes:
        return await message.answer("❌ CODE salah")

    codes = list(dict.fromkeys(codes))[:3]

    all_data = []

    for code in codes:

        data = await load_media(code)

        if data:
            all_data.extend(data)

        await asyncio.sleep(0.1)

    if not all_data:
        return await message.answer("❌ Tidak ditemukan")

    all_data = all_data[:50]

    # =========================
    # HAPUS PANEL LAMA
    # =========================

    old_state = user_states.get(user_id)

    if old_state:

        old_panel = old_state.get(
            "last_panel_msg"
        )

        if old_panel:

            try:

                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=old_panel
                )

            except Exception:
                pass

    # =========================
    # BUAT SESSION BARU
    # =========================

    user_states[user_id] = {
        "mode": "view",
        "code": codes[0],
        "page": 0,
        "page_size": 5,
        "data": all_data,
        "last_panel_msg": None
    }

    page_history[user_id] = set()

    await message.answer(
        f"📦 Ditemukan {len(all_data)} file"
    )

    # =========================
    # RENDER PAGE PERTAMA
    # =========================

    await render_page(
        user_id,
        message.bot,
        message.chat.id
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

    # =========================
    # SAVE USER
    # =========================
    await add_user(
        user.id,
        user.username or "",
        user.full_name or "No Name"
    )

    async with db_pool.acquire() as conn:

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
    # FORMAT CODE LIST
    # =========================
    if codes:
        code_lines = []
        for c in codes:
            code_lines.append(
                f"📦 <code>{c['code']}</code>\n"
                f"   └ {c['total_media']} file"
            )

        code_text = "\n".join(code_lines)

    else:
        code_text = "❌ Belum ada code"

    # =========================
    # FORMAT USER
    # =========================
    username = f"@{user.username}" if user.username else "Tidak ada"

    text = (
        "👤 <b>ACCOUNT INFO</b>\n\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"👤 <b>Name:</b> {user.full_name}\n"
        f"🔗 <b>Username:</b> {username}\n\n"
        f"📊 <b>Total Code:</b> {total_codes}\n\n"
        f"📁 <b>Last Code:</b>\n{code_text}"
    )

    await message.answer(text, parse_mode="HTML")
# =========================
# VIP KEYBOARD
# =========================
def vip_kb():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 CHAT ADMIN VIP",
                    url="https://t.me/penngewe"
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
# =========================
# VIP COMMAND
# =========================
@router.message(F.text == "/vip")
async def vip_cmd(message: Message):

    text = (
        "💎 <b>VIP ACCESS</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        "🔥 <b>BENEFIT VIP</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "⚡ Unlimited Upload File\n"
        "⚡ Priority Processing (No Queue)\n"
        "⚡ Fast Get File Access\n"
        "⚡ Anti Limit System\n"
        "⚡ Full Media Support\n\n"
        "━━━━━━━━━━━━━━\n"
        "📦 <b>STORAGE INFO</b>\n"
        "━━━━━━━━━━━━━━\n"
        "📁 Media disimpan di channel database\n"
        "🔒 Aman via CODE system\n\n"
        "━━━━━━━━━━━━━━\n"
        "💀 <b>NOTICE</b>\n"
        "━━━━━━━━━━━━━━\n"
        "• VIP = akses, bukan privilege manja\n"
        "• Semua tetap pakai sistem\n"
        "• Salah pakai = tanggung sendiri 😏"
    )

    await message.answer(
        text,
        reply_markup=vip_kb(),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# =========================
# VIP CANCEL
# =========================
@router.callback_query(F.data == "vip_cancel")
async def vip_cancel(call: CallbackQuery):

    try:
        await call.message.edit_text(
            "❌ <b>VIP CLOSED</b>\n\n"
            "😏 Balik ke mode gratisan.\n"
            "Kalau serius, jangan cuma klik.",
            parse_mode="HTML"
        )
    except:
        pass

    await call.answer()
# =========================
# ADMIN CHECK
# =========================
def is_admin(user_id: int):
    return user_id in ADMINS


# =========================
# ADD ADMIN
# =========================
@router.message(F.text.startswith("/addadmin"))
async def add_admin(message: Message):

    if not is_admin(message.from_user.id):
        return await message.answer(
            "🚫 ACCESS DENIED\n\nLu siapa 😏"
        )

    parts = message.text.split()

    if len(parts) != 2:
        return await message.answer(
            "❌ Format:\n/addadmin <user_id>"
        )

    # =========================
    # VALIDATE
    # =========================
    try:
        uid = int(parts[1])
    except:
        return await message.answer("❌ ID harus angka")

    # =========================
    # PREVENT DUPLICATE
    # =========================
    if uid in ADMINS:
        return await message.answer(
            "⚠️ Sudah admin 😏"
        )

    # =========================
    # ADD
    # =========================
    ADMINS.add(uid)

    print(f"[ADMIN] Added: {uid} by {message.from_user.id}")

    await message.answer(
        f"💀 ADMIN ADDED\n\nID: {uid}"
    )


# =========================
# REMOVE ADMIN (WAJIB ADA)
# =========================
@router.message(F.text.startswith("/deladmin"))
async def del_admin(message: Message):

    if not is_admin(message.from_user.id):
        return await message.answer("🚫 No access")

    parts = message.text.split()

    if len(parts) != 2:
        return await message.answer(
            "❌ Format:\n/deladmin <user_id>"
        )

    try:
        uid = int(parts[1])
    except:
        return await message.answer("❌ ID invalid")

    # =========================
    # PROTECT
    # =========================
    if uid == message.from_user.id:
        return await message.answer(
            "⚠️ Gak bisa hapus diri sendiri 😏"
        )

    if uid not in ADMINS:
        return await message.answer(
            "❌ Bukan admin"
        )

    ADMINS.remove(uid)

    print(f"[ADMIN] Removed: {uid} by {message.from_user.id}")

    await message.answer(
        f"💀 ADMIN REMOVED\n\nID: {uid}"
    )

# =========================
# STATISTIC (UPGRADE)
# =========================
@router.message(F.text == "/stat")
async def stat_cmd(message: Message):

    if not is_admin(message.from_user.id):
        return await message.answer("🚫 ACCESS DENIED")

    try:
        async with db_pool.acquire() as conn:

            users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
            codes = await conn.fetchval("SELECT COUNT(*) FROM codes") or 0
            media = await conn.fetchval("SELECT COUNT(*) FROM medias") or 0

            total_size = await conn.fetchval(
                "SELECT COALESCE(SUM(total_size),0) FROM codes"
            ) or 0

    except Exception as e:
        print("STAT ERROR:", e)
        return await message.answer("⚠️ DATABASE ERROR")

    mb = total_size / (1024 * 1024)

    await message.answer(
        "📊 <b>SYSTEM STATISTICS</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        f"👤 Users   : {users}\n"
        f"🔑 Codes   : {codes}\n"
        f"📦 Media   : {media}\n"
        f"💾 Storage : {mb:.2f} MB\n"
        "━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )


# =========================
# BROADCAST (DEWA VERSION)
# =========================
@router.message(F.text.startswith("/broadcast"))
async def broadcast_cmd(message: Message):

    if not is_admin(message.from_user.id):
        return await message.answer("🚫 ACCESS DENIED")

    text = message.text.replace("/broadcast", "").strip()

    if not text:
        return await message.answer("❌ Format:\n/broadcast pesan")

    # =========================
    # LOAD USERS
    # =========================
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users")
    except Exception as e:
        print("BC ERROR:", e)
        return await message.answer("⚠️ DATABASE ERROR")

    total = len(users)
    sent = 0
    failed = 0

    start_time = time.time()

    status = await message.answer(
        f"📡 <b>BROADCAST STARTED</b>\n\n"
        f"👥 Total user: {total}\n"
        f"⏳ Progress: 0%\n\n"
        "💀 System running...",
        parse_mode="HTML"
    )

    # =========================
    # LOOP
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
        # SMART DELAY (ANTI BANNED)
        # =========================
        if i % 20 == 0:
            await asyncio.sleep(1.2)  # heavy pause
        else:
            await asyncio.sleep(random.uniform(0.03, 0.1))  # normal delay

        # =========================
        # UPDATE PROGRESS (SETIAP 25 USER)
        # =========================
        if i % 25 == 0:
            percent = (i / total) * 100

            try:
                await status.edit_text(
                    f"📡 <b>BROADCAST RUNNING</b>\n\n"
                    f"👥 Total   : {total}\n"
                    f"📤 Sent    : {sent}\n"
                    f"❌ Failed  : {failed}\n"
                    f"⏳ Progress: {percent:.1f}%\n\n"
                    "⚡ Please wait...",
                    parse_mode="HTML"
                )
            except:
                pass

    # =========================
    # DONE
    # =========================
    duration = time.time() - start_time

    await status.edit_text(
        "📡 <b>BROADCAST FINISHED</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        f"👥 Total   : {total}\n"
        f"📤 Sent    : {sent}\n"
        f"❌ Failed  : {failed}\n"
        f"⏱ Time    : {duration:.1f}s\n"
        "━━━━━━━━━━━━━━\n\n"
        "💀 Mission complete 😏",
        parse_mode="HTML"
    )

# =========================
# HELP TEXT
# =========================
HELP_TEXT = """
<b>🔥 TZY FILE BOT — HELP MENU 🔥</b>

Selamat datang di <b>TZY FILE BOT</b>
Bot untuk upload & ambil file pakai <code>CODE</code>

━━━━━━━━━━━━━━
📤 <b>UPLOAD FILE</b>
━━━━━━━━━━━━━━
1. Tekan <b>📤 Up File</b>
2. Kirim media
3. Tekan <b>✅ DONE</b>
4. Bot kasih CODE

⚠️ Jangan lupa DONE!

━━━━━━━━━━━━━━
📥 <b>GET FILE</b>
━━━━━━━━━━━━━━
1. Tekan <b>📥 Get File</b>
2. Kirim CODE
3. File dikirim otomatis

❌ Kalau error:
• CODE salah
• Tidak ditemukan

━━━━━━━━━━━━━━
👤 <b>ACCOUNT</b>
━━━━━━━━━━━━━━
• ID
• Nama
• Username

━━━━━━━━━━━━━━
💎 <b>VIP</b>
━━━━━━━━━━━━━━
⚡ Unlimited Upload  
⚡ Faster Access  
⚡ Priority System  

━━━━━━━━━━━━━━
🛠 <b>ADMIN</b>
━━━━━━━━━━━━━━
<code>/stat</code> → statistik  
<code>/broadcast</code> → kirim ke semua user  
<code>/addadmin</code> → tambah admin  

━━━━━━━━━━━━━━
⚠ <b>RULE</b>
━━━━━━━━━━━━━━
❌ Spam  
❌ Abuse  
❌ Flood  

━━━━━━━━━━━━━━
💀 <b>NOTE</b>
━━━━━━━━━━━━━━
• Bot bukan cenayang 😏  
• Salah input = salah sendiri  
• Simpan CODE baik-baik  

━━━━━━━━━━━━━━
🚀 <b>READY</b>
━━━━━━━━━━━━━━
"""

# =========================
# HELP HANDLER
# =========================
@router.message(F.text == "/help")
async def help_cmd(message: Message):

    await asyncio.sleep(0.2)

    await message.answer(
        HELP_TEXT,
        parse_mode="HTML"
    )


@router.message(F.text == "❓ Help")
async def help_button(message: Message):

    await asyncio.sleep(0.2)

    await message.answer(
        HELP_TEXT,
        parse_mode="HTML"
    )

# =========================
# CLEANUP MEMORY
# =========================

async def cleanup_task():

    while True:

        await asyncio.sleep(600)

        now = time.time()

        for uid in list(user_last_action):

            # 6 JAM TIDAK AKTIF
            if now - user_last_action[uid] > 21600:

                user_last_action.pop(uid, None)

                page_history.pop(uid, None)

                user_states.pop(uid, None)

                upload_sessions.pop(uid, None)

                last_edit_time.pop(uid, None)

                page_cooldown.pop(uid, None)

                user_click_lock.pop(uid, None)

# =========================
# STARTUP
# =========================
async def main():

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(router)

    await init_db()

    # =========================
    # START BACKGROUND TASK
    # =========================
    asyncio.create_task(
        cleanup_task()
    )

    print("🔥 BOT STARTED")

    try:
        await dp.start_polling(bot)

    except Exception as e:

        print(
            "❌ BOT ERROR:",
            e
        )

    finally:

        print("💀 SHUTDOWN...")

        if db_pool:
            await db_pool.close()

        await bot.session.close()
# =========================
# RUN
# =========================
if __name__ == "__main__":
    asyncio.run(main())
