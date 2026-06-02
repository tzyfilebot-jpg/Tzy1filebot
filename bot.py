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

FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL")
NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL")
VIP_LINK = os.getenv("VIP_LINK")

# =========================
# DB POOL (OPTIMIZED)
# =========================

db_pool: asyncpg.Pool | None = None

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        statement_cache_size=100,   # FIX
        command_timeout=15          # FIX
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

# =========================
# ANTI BANNED SYSTEM 🔥
# =========================

GLOBAL_DELAY = 0.05
last_global_send = 0

USER_DELAY = 2
user_last_action = {}

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
# MEDIA SENDER (SAFE)
# =========================

async def send_media(bot, chat_id: int, chunk: list):

    if not chunk:
        return

    media_group = []

    for m in chunk[:5]:
        file_type = (m.get("file_type") or "").lower()
        file_id = m.get("file_id")

        if not file_id:
            continue

        if file_type == "photo":
            media_group.append(InputMediaPhoto(media=file_id))

        elif file_type == "video":
            media_group.append(InputMediaVideo(media=file_id))

        else:
            media_group.append(InputMediaDocument(media=file_id))

    if not media_group:
        return

    await safe_send(
        bot.send_media_group,
        chat_id=chat_id,
        media=media_group
    )

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
# FORCE SUB (SAFE + CLEAN)
# =========================

async def check_force_sub(bot: Bot, user_id: int, channel: str):
    try:
        ch = channel.replace("@", "").strip()

        member = await bot.get_chat_member(
            chat_id=f"@{ch}",
            user_id=user_id
        )

        return member.status in ("member", "administrator", "creator")

    except Exception as e:
        print("FORCE SUB ERROR:", e)
        return False


def force_kb(channel):
    ch = channel.replace("@", "").strip()

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Join Channel",
                    url=f"https://t.me/{ch}"
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
# START (ANTI BANNED VERSION)
# =========================

@router.message(F.text == "/start")
async def start(message: Message, bot: Bot):

    user = message.from_user

    # 🔥 ANTI SPAM USER
    if not user_limit(user.id):
        return await safe_send(
            message.answer,
            "⏳ Jangan spam ya 😏"
        )

    # =========================
    # FORCE SUB CHECK
    # =========================
    if FORCE_CHANNEL:
        ok = await check_force_sub(bot, user.id, FORCE_CHANNEL)

        if not ok:
            return await safe_send(
                message.answer,
                "⚠️ AKSES DITOLAK\n\n"
                "😏 Kamu belum join channel.\n"
                "Join dulu baru bisa lanjut.",
                reply_markup=force_kb(FORCE_CHANNEL)
            )

    # =========================
    # SAVE USER (SAFE)
    # =========================
    try:
        await add_user(
            user.id,
            user.username or "none",
            user.full_name
        )
    except Exception as e:
        print("ADD USER ERROR:", e)

    # =========================
    # RESPONSE
    # =========================
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
# CHECK SUB (ANTI SPAM + SAFE EDIT)
# =========================

@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery, bot: Bot):

    user_id = call.from_user.id

    # 🔥 ANTI SPAM
    if not user_limit(user_id):
        return await call.answer("⏳ Jangan spam", show_alert=True)

    if not FORCE_CHANNEL:
        return await call.answer("Force sub OFF", show_alert=True)

    ok = await check_force_sub(bot, user_id, FORCE_CHANNEL)

    if not ok:
        return await call.answer(
            "❌ Kamu belum join channel",
            show_alert=True
        )

    # =========================
    # SUCCESS
    # =========================
    try:
        await call.message.edit_text("✅ VERIFIED")
    except:
        pass

    await safe_send(
        call.message.answer,
        "🔥 AKSES DIBUKA\n\n"
        "😏 Silakan gunakan bot.",
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
                InlineKeyboardButton(text="✅ DONE", callback_data="upload_done"),
                InlineKeyboardButton(text="❌ CANCEL", callback_data="upload_cancel")
            ]
        ]
    )


@router.message(F.text == "📤 Up File")
async def up_file(message: Message):

    user_id = message.from_user.id

    if not user_limit(user_id):
        return await safe_send(message.answer, "⏳ Jangan spam ya 😏")

    # reset session
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

    msg = await safe_send(
        message.answer,
        "📤 UPLOAD MODE AKTIF\n\n"
        "😏 Kirim file kamu sekarang.\n"
        "Tekan DONE kalau sudah.\n\n"
        "💀 Jangan lama-lama ya...",
        reply_markup=upload_kb()
    )

    upload_sessions[user_id]["msg_id"] = msg.message_id


# =========================
# MEDIA HANDLER (FINAL CLEAN)
# =========================

@router.message(F.photo | F.video | F.document)
async def handle_media(message: Message):

    user_id = message.from_user.id

    state = user_states.get(user_id)
    s = upload_sessions.get(user_id)

    if not state or state.get("mode") != "upload":
        return

    if not s or not s.get("msg_id"):
        return

    # =========================
    # GET FILE
    # =========================
    if message.photo:
        file_obj = message.photo[-1]
        s["photo"] += 1

    elif message.video:
        file_obj = message.video
        s["video"] += 1

    elif message.document:
        file_obj = message.document
        s["document"] += 1

    else:
        return

    file_id = file_obj.file_id
    size = getattr(file_obj, "file_size", 0) or 0

    s["items"].append({
        "file_id": file_id,
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
    # THROTTLE
    # =========================
    now = time.time()
    if now - last_edit_time.get(user_id, 0) < 1:
        return
    last_edit_time[user_id] = now

    # =========================
    # STATS + UI (SATU KALI EDIT)
    # =========================
    total = len(s["items"])
    size_mb = round(sum(x["size"] for x in s["items"]) / (1024 * 1024), 2)

    bar_len = 10
    filled = min(bar_len, total)
    bar = "█" * filled + "░" * (bar_len - filled)

    text = (
        "📤 UPLOAD MODE\n\n"
        f"📊 Progress : [{bar}] {total} file\n\n"
        f"🖼 Photo    : {s['photo']}\n"
        f"🎬 Video    : {s['video']}\n"
        f"📁 Document : {s['document']}\n"
        f"💾 Size     : {size_mb} MB\n\n"
        "━━━━━━━━━━━━━━\n"
        "Tekan DONE kalau sudah 😏"
    )

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

    return f"tzy_{v}v_{p}p_{d}d_{rand}"


# =========================
# DONE HANDLER
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

    try:
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
            # UPLOAD TO CHANNEL
            # =========================
            for m in s["items"]:

                file_id = m.get("file_id")
                file_type = m.get("type")

                if not file_id or not file_type:
                    continue

                try:
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

                    elif file_type == "document":
                        msg = await call.bot.send_document(
                            chat_id=CHANNEL_DB,
                            document=file_id
                        )
                        new_file_id = msg.document.file_id

                    else:
                        continue

                    saved_items.append(
                        (code, new_file_id, file_type, m.get("size", 0))
                    )

                except Exception as e:
                    print("UPLOAD ERROR:", e)
                    continue

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

    except Exception as e:
        print("DB ERROR:", e)
        return await call.message.edit_text(
            "❌ Gagal menyimpan file, coba lagi nanti"
        )

    # =========================
    # CLEAN SESSION
    # =========================
    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)
    last_edit_time.pop(user_id, None)

    # =========================
    # FINAL RESPONSE
    # =========================
    try:
        await call.message.edit_text(
            "💀 UPLOAD COMPLETE\n\n"
            f"😏 CODE: <code>{code}</code>\n\n"
            f"📦 Total File : {total_items}\n"
            f"💾 Size      : {round(total_size / (1024 * 1024), 2)} MB\n\n"
            "📦 File berhasil disimpan 😏\n"
            "🤖 Bot: tzyfilerobot",
            parse_mode="HTML"
        )
    except Exception as e:
        print("FINAL EDIT ERROR:", e)


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
page_history = {}
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
        return

    media = []

    for m in chunk[:5]:
        fid = m.get("file_id")
        t = m.get("file_type")

        if not fid:
            continue

        if t == "photo":
            media.append(InputMediaPhoto(media=fid))
        elif t == "video":
            media.append(InputMediaVideo(media=fid))
        else:
            media.append(InputMediaDocument(media=fid))

    if not media:
        return

    try:
        await bot.send_media_group(chat_id, media)
        await asyncio.sleep(0.3 + random.uniform(0.1, 0.4))
    except Exception as e:
        print("SEND ERROR:", e)


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

    return InlineKeyboardMarkup(inline_keyboard=rows)


# =========================
# RENDER PAGE (CORE)
# =========================
async def render_page(call, user_id):

    state = user_states.get(user_id)
    if not state:
        return await call.answer("Session expired")

    data = state.get("data") or []
    if not data:
        return await call.answer("No data")

    page = state.get("page", 0)
    size = state.get("page_size", 5)

    total = max(1, (len(data) + size - 1) // size)

    # clamp
    page = max(0, min(page, total - 1))
    state["page"] = page

    page_history.setdefault(user_id, set()).add(page)

    start = page * size
    chunk = data[start:start + size]

    # SEND MEDIA
    await send_media(call.bot, call.message.chat.id, chunk)

    text = (
        f"📦 CODE: <code>{state['code']}</code>\n"
        f"📄 Page: {page+1}/{total}\n"
        f"📁 Media: {start+1}-{start+len(chunk)} / {len(data)}"
    )

    kb = build_kb(user_id, page, total)

    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except:
        pass

    await call.answer()


# =========================
# SINGLE PAGINATION HANDLER
# =========================
@router.callback_query(
    F.data.in_(["next", "prev"]) | F.data.startswith("page:")
)
async def pagination(call: CallbackQuery):

    user_id = call.from_user.id
    state = user_states.get(user_id)

    if not state:
        return await call.answer("Session expired")

    data = state.get("data") or []
    if not data:
        return await call.answer("No data")

    page = state.get("page", 0)
    size = state.get("page_size", 5)
    max_page = (len(data) - 1) // size

    if call.data == "next":
        page += 1
    elif call.data == "prev":
        page -= 1
    else:
        try:
            page = int(call.data.split(":")[1])
        except:
            return await call.answer("Error")

    page = max(0, min(page, max_page))
    state["page"] = page

    await render_page(call, user_id)


# =========================
# NOOP
# =========================
@router.callback_query(F.data == "noop")
async def noop(call):
    await call.answer("😏")


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

    codes = re.findall(r"\btzy_[A-Za-z0-9_]+\b", message.text or "")

    if not codes:
        return await message.answer("❌ CODE salah")

    codes = list(dict.fromkeys(codes))[:3]

    all_data = []

    for code in codes:
        data = await load_media(code)
        if data:
            all_data.extend(data)
        await asyncio.sleep(0.15)

    if not all_data:
        return await message.answer("❌ Tidak ditemukan")

    # LIMIT
    all_data = all_data[:50]

    # SAVE STATE (PAGINATION MODE)
    user_states[user_id] = {
        "mode": "view",
        "code": codes[0],
        "page": 0,
        "page_size": 5,
        "data": all_data
    }

    page_history[user_id] = set()

    await message.answer(f"📦 Ditemukan {len(all_data)} file")

    # RENDER PAGE PERTAMA
    fake_call = type("obj", (), {
        "bot": message.bot,
        "message": message,
        "answer": message.answer
    })

    await render_page(fake_call, user_id)
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

    if not VIP_LINK:
        return None

    link = VIP_LINK.replace("https://t.me/", "").replace("@", "").strip()

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
from aiogram import F, Router
from aiogram.types import Message
import asyncio
import time

router = Router()

# =========================
# ADMIN CHECK
# =========================
def is_admin(user_id: int):
    return user_id in ADMINS


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
            await asyncio.sleep(0.04)  # normal delay

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
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message
import asyncio

router = Router()

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
# STARTUP
# =========================
async def main():

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(router)

    await init_db()

    print("🔥 BOT STARTED")

    try:
        await dp.start_polling(bot)

    except Exception as e:
        print("❌ BOT ERROR:", e)

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
