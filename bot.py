# =========================
# IMPORT
# =========================

import os
import time
import asyncio
from typing import Dict

import asyncpg
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest

# =========================
# CONFIG
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

FORCE_CHANNEL = os.getenv("FORCE_CHANNEL", "")
VIP_LINK = os.getenv("VIP_LINK", "")

# safe admin parsing
ADMINS = set()
raw_admins = os.getenv("ADMINS", "")
if raw_admins:
    for x in raw_admins.split(","):
        x = x.strip()
        if x.isdigit():
            ADMINS.add(int(x))

# =========================
# DB POOL
# =========================

db_pool: asyncpg.Pool | None = None

# =========================
# MEMORY
# =========================

user_states: Dict[int, dict] = {}

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
                KeyboardButton(text="📥 Get File"),
            ]
        ],
        resize_keyboard=True
    )

# =========================
# FORCE SUB CHECK
# =========================

async def check_force_sub(bot: Bot, user_id: int, channel: str) -> bool:
    if not channel:
        return True

    try:
        channel = channel.replace("@", "").strip()

        member = await bot.get_chat_member(
            chat_id=f"@{channel}",
            user_id=user_id
        )

        return member.status in ("member", "administrator", "creator", "restricted")

    except Exception as e:
        print("FORCE SUB ERROR:", e)
        return False


def force_kb(channel: str):
    channel = channel.replace("@", "").strip()

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Join Channel",
                    url=f"https://t.me/{channel}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Verify",
                    callback_data="check_sub"
                )
            ]
        ]
    )

# =========================
# SAFE ADD USER (FIX BIAR GA CRASH)
# =========================

async def add_user(user_id: int, username: str, fullname: str):
    """
    Placeholder biar bot tidak error kalau DB belum siap.
    Nanti nyambung ke PostgreSQL di file utama kamu.
    """
    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users(user_id, username, fullname)
            VALUES($1,$2,$3)
            ON CONFLICT(user_id)
            DO UPDATE SET username=$2, fullname=$3
            """,
            user_id,
            username,
            fullname
        )

# =========================
# START COMMAND
# =========================

@router.message(F.text == "/start")
async def start(message: Message, bot: Bot):

    user = message.from_user

    # FORCE SUB
    if FORCE_CHANNEL:
        verified = await check_force_sub(bot, user.id, FORCE_CHANNEL)

        if not verified:
            return await message.answer(
                "⚠️ ACCESS BLOCKED\n\nJoin channel dulu untuk pakai bot.",
                reply_markup=force_kb(FORCE_CHANNEL)
            )

    # SAVE USER
    try:
        await add_user(
            user.id,
            user.username or "none",
            user.full_name or "Unknown"
        )
    except Exception as e:
        print("ADD USER ERROR:", e)

    # MENU
    await message.answer(
        "🔥 BOT ONLINE\n\n"
        "📤 Up File → upload file\n"
        "📥 Get File → ambil file dari CODE\n\n"
        "Simpan CODE kamu baik-baik.",
        reply_markup=get_keyboard()
    )

# =========================
# CHECK SUB CALLBACK
# =========================

@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery, bot: Bot):

    if not FORCE_CHANNEL:
        return await call.answer("Force sub disabled", show_alert=True)

    verified = await check_force_sub(bot, call.from_user.id, FORCE_CHANNEL)

    if not verified:
        return await call.answer("Belum join channel", show_alert=True)

    try:
        await call.message.edit_text("✅ VERIFIED")
    except TelegramBadRequest:
        pass

    await call.message.answer("🔥 Access granted", reply_markup=get_keyboard())
    await call.answer()
# =========================
# UPLOAD CONFIG
# =========================

MAX_FILES = 300
SESSION_TIMEOUT = 3600

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

# =========================
# OPEN UPLOAD MODE
# =========================

@router.message(F.text == "📤 Up File")
async def up_file(message: Message):

    user_id = message.from_user.id

    upload_sessions[user_id] = {
        "video": 0,
        "photo": 0,
        "document": 0,
        "items": [],
        "msg_id": None,
        "created": time.time(),
        "processing": False
    }

    user_states[user_id] = {
        "mode": "upload"
    }

    msg = await message.answer(
        "📤 Upload mode aktif\n\n"
        "Kirim file lalu tekan DONE",
        reply_markup=upload_kb()
    )

    upload_sessions[user_id]["msg_id"] = msg.message_id

# =========================
# MEDIA HANDLER
# =========================

@router.message(
    F.photo | F.video | F.document
)
async def handle_media(
    message: Message
):

    user_id = message.from_user.id

    state = user_states.get(user_id)
    session = upload_sessions.get(user_id)

    if not state:
        return

    if state.get("mode") != "upload":
        return

    if not session:
        return

    if time.time() - session["created"] > SESSION_TIMEOUT:

        upload_sessions.pop(user_id, None)

        return await message.answer(
            "Session expired"
        )

    if len(session["items"]) >= MAX_FILES:

        return await message.answer(
            "Limit file tercapai"
        )

    if message.photo:

        obj = message.photo[-1]

        session["photo"] += 1

        file_type = "photo"

    elif message.video:

        obj = message.video

        session["video"] += 1

        file_type = "video"

    else:

        obj = message.document

        session["document"] += 1

        file_type = "document"

    session["items"].append({

        "file_id": obj.file_id,

        "file_type": file_type,

        "size": getattr(
            obj,
            "file_size",
            0
        ) or 0

    })

    try:
        await message.delete()
    except:
        pass

    now = time.time()

    if now - last_edit_time.get(user_id, 0) < 1:
        return

    last_edit_time[user_id] = now

    total_size = sum(
        x["size"]
        for x in session["items"]
    )

    try:

        await message.bot.edit_message_text(

            chat_id=user_id,

            message_id=session["msg_id"],

            text=(
                f"📦 File : {len(session['items'])}\n"
                f"🎥 {session['video']}\n"
                f"🖼 {session['photo']}\n"
                f"📁 {session['document']}\n"
                f"💾 {round(total_size/1024/1024,2)} MB"
            ),

            reply_markup=upload_kb()

        )

    except TelegramBadRequest:
        pass

# =========================
# CODE GENERATOR
# =========================

def generate_code(
    v,
    p,
    d
):

    import hashlib

    seed = (
        f"{v}{p}{d}"
        f"{time.time()}"
        f"{secrets.token_hex(5)}"
    )

    return (
        "tzy_" +
        hashlib.sha1(
            seed.encode()
        ).hexdigest()[:18]
    )

# =========================
# DONE
# =========================

@router.callback_query(
    F.data == "upload_done"
)
async def done(
    call: CallbackQuery
):

    user_id = call.from_user.id

    session = upload_sessions.get(
        user_id
    )

    if not session:

        return await call.answer(
            "Session expired",
            show_alert=True
        )

    if session["processing"]:

        return await call.answer()

    session["processing"] = True

    if not session["items"]:

        session["processing"] = False

        return await call.answer(
            "Upload kosong",
            show_alert=True
        )

    if not CHANNEL_DB:

        session["processing"] = False

        return await call.answer(
            "CHANNEL_DB missing",
            show_alert=True
        )

    code = generate_code(

        session["video"],

        session["photo"],

        session["document"]

    )

    total_size = sum(
        x["size"]
        for x in session["items"]
    )

    try:

        async with db_pool.acquire() as conn:

            async with conn.transaction():

                await conn.execute(
                    """
                    INSERT INTO codes
                    (code,owner_id,total_media,total_size)

                    VALUES($1,$2,$3,$4)
                    """,

                    code,

                    user_id,

                    len(session["items"]),

                    total_size
                )

                rows = []

                for item in session["items"]:

                    if item["file_type"] == "photo":

                        sent = await call.bot.send_photo(
                            CHANNEL_DB,
                            item["file_id"]
                        )

                        new_file_id = sent.photo[-1].file_id

                    elif item["file_type"] == "video":

                        sent = await call.bot.send_video(
                            CHANNEL_DB,
                            item["file_id"]
                        )

                        new_file_id = sent.video.file_id

                    else:

                        sent = await call.bot.send_document(
                            CHANNEL_DB,
                            item["file_id"]
                        )

                        new_file_id = sent.document.file_id

                    rows.append(

                        (
                            code,
                            new_file_id,
                            sent.message_id,
                            item["file_type"],
                            item["size"]
                        )

                    )

                await conn.executemany(
                    """
                    INSERT INTO medias
                    (code,file_id,message_id,file_type,file_size)

                    VALUES($1,$2,$3,$4,$5)
                    """,
                    rows
                )

    finally:

        upload_sessions.pop(
            user_id,
            None
        )

        user_states.pop(
            user_id,
            None
        )

        last_edit_time.pop(
            user_id,
            None
        )

    await call.message.edit_text(

        "✅ Upload selesai\n\n"

        f"<code>{code}</code>",

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

    uid = call.from_user.id

    upload_sessions.pop(
        uid,
        None
    )

    user_states.pop(
        uid,
        None
    )

    last_edit_time.pop(
        uid,
        None
    )

    await call.message.edit_text(
        "Upload dibatalkan"
    )
# =========================
# GET FILE MODE
# =========================

GETFILE_COOLDOWN = {}
STATE_TIMEOUT = 1800  # 30 menit

@router.message(F.text == "📥 Get File")
async def get_file_start(message: Message):

    user_id = message.from_user.id

    user_states[user_id] = {
        "mode": "getfile",
        "created": time.time()
    }

    await message.answer(
        "📥 Kirim CODE untuk ambil file\n\n"
        "⚡ Maksimal 10 CODE sekaligus"
    )


# =========================
# NORMALIZER
# =========================

def normalize_type(t: str):

    t = (t or "").lower().strip()

    mapping = {
        "photo": "photo",
        "image": "photo",
        "img": "photo",

        "video": "video",
        "vid": "video",

        "doc": "document",
        "document": "document",
        "file": "document"
    }

    return mapping.get(t, "document")


# =========================
# LOAD MEDIA SAFE
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
                COALESCE(file_size,0) file_size

            FROM medias

            WHERE code=$1

            ORDER BY id ASC

            LIMIT 300
            """,
            code
        )

    return [
        {
            "file_id": r["file_id"],
            "file_type": normalize_type(
                r["file_type"]
            ),
            "file_size": r["file_size"]
        }
        for r in rows
    ]


# =========================
# SEND MEDIA SAFE
# =========================

async def send_media(
    bot,
    chat_id: int,
    chunk: list
):

    if not chunk:
        return

    media = []

    for m in chunk[:5]:

        file_id = m.get("file_id")

        if not file_id:
            continue

        typ = m.get("file_type")

        try:

            if typ == "photo":
                media.append(
                    InputMediaPhoto(
                        media=file_id
                    )
                )

            elif typ == "video":
                media.append(
                    InputMediaVideo(
                        media=file_id
                    )
                )

            else:
                media.append(
                    InputMediaDocument(
                        media=file_id
                    )
                )

        except:
            continue

    if not media:
        return

    try:

        await bot.send_media_group(
            chat_id=chat_id,
            media=media
        )

    except TelegramRetryAfter as e:

        await asyncio.sleep(
            e.retry_after
        )

        await bot.send_media_group(
            chat_id=chat_id,
            media=media
        )

    except Exception as e:

        print(
            "SEND MEDIA ERROR:",
            e
        )


# =========================
# RECEIVE CODE
# =========================

@router.message(
    F.text &
    ~F.text.startswith("/")
)
async def receive_code(message: Message):

    user_id = message.from_user.id

    state = user_states.get(
        user_id
    )

    if not state:
        return

    if state.get("mode") != "getfile":
        return

    # timeout cleanup
    if time.time() - state.get(
        "created",
        time.time()
    ) > STATE_TIMEOUT:

        user_states.pop(
            user_id,
            None
        )

        return await message.answer(
            "⌛ Session expired"
        )

    # cooldown
    now = time.time()

    if now - GETFILE_COOLDOWN.get(
        user_id,
        0
    ) < 2:

        return

    GETFILE_COOLDOWN[user_id] = now

    text = (
        message.text or ""
    ).strip()

    codes = re.findall(
        r"[A-Za-z0-9_]{6,}",
        text
    )

    codes = list(
        dict.fromkeys(codes)
    )[:10]

    if not codes:

        return await message.answer(
            "❌ CODE tidak ditemukan"
        )

    all_data = []

    for code in codes:

        try:

            media = await load_media(
                code
            )

            if media:
                all_data.extend(
                    media
                )

        except Exception as e:

            print(
                "LOAD:",
                e
            )

    if not all_data:

        return await message.answer(
            "❌ CODE invalid"
        )

    # max memory safety
    all_data = all_data[:500]

    user_states[user_id] = {

        "mode": "view",

        "page": 0,

        "code": codes[0],

        "data": all_data,

        "created": time.time()
    }

    page_history[user_id] = set()

    await render_first_page(
        message,
        user_id
    )
        
# =========================
# PAGINATION CONFIG
# =========================

PAGE_SIZE = 5
CALLBACK_COOLDOWN = {}
PAGE_LOCK = {}

# =========================
# KEYBOARD BUILDER
# =========================

def build_kb(user_id, page, total_pages):

    history = page_history.setdefault(
        user_id,
        set()
    )

    # limit history memory
    if len(history) > 100:
        history.clear()

    rows = []

    rows.append([
        InlineKeyboardButton(
            text="⬅ Prev",
            callback_data="prev"
        ),
        InlineKeyboardButton(
            text="➡ Next",
            callback_data="next"
        )
    ])

    row = []

    start = max(
        0,
        page - 2
    )

    end = min(
        total_pages,
        start + 5
    )

    for i in range(start, end):

        if i == page:
            mark = "🟢"

        elif i in history:
            mark = "🟡"

        else:
            mark = "⚪"

        row.append(

            InlineKeyboardButton(
                text=f"{i+1}{mark}",
                callback_data=f"page:{i}"
            )
        )

    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            text="📢 JOIN",
            url="https://t.me/+slzhVF3Lev0zZTRh"
        ),
        InlineKeyboardButton(
            text="💬 GROUP",
            url="https://t.me/gcbotkx"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


# =========================
# RENDER CORE
# =========================

async def render_page_data(
    bot,
    chat_id,
    state,
    user_id
):

    page = state["page"]

    data = state["data"]

    start = page * PAGE_SIZE

    chunk = data[
        start:
        start + PAGE_SIZE
    ]

    total_pages = max(
        1,
        (len(data) + PAGE_SIZE - 1)
        // PAGE_SIZE
    )

    await send_media(
        bot,
        chat_id,
        chunk
    )

    text = (

        f"📦 CODE: {state['code']}\n"

        f"📄 Page: {page+1}/{total_pages}\n"

        f"📁 Media: "

        f"{start+1}-"

        f"{start+len(chunk)}"

        f"/{len(data)}"
    )

    kb = build_kb(
        user_id,
        page,
        total_pages
    )

    return text, kb


# =========================
# FIRST RENDER
# =========================

async def render_first_page(
    message,
    user_id
):

    state = user_states.get(
        user_id
    )

    if not state:

        return await message.answer(
            "Session expired"
        )

    state["page"] = 0

    text, kb = await render_page_data(
        message.bot,
        message.chat.id,
        state,
        user_id
    )

    msg = await message.answer(
        text,
        reply_markup=kb
    )

    state["msg_id"] = msg.message_id


# =========================
# PAGE RENDER
# =========================

async def render_page(
    call,
    user_id
):

    if PAGE_LOCK.get(user_id):

        return await call.answer(
            "Wait..."
        )

    PAGE_LOCK[user_id] = True

    try:

        state = user_states.get(
            user_id
        )

        if not state:

            return await call.answer(
                "Expired"
            )

        text, kb = await render_page_data(
            call.bot,
            call.message.chat.id,
            state,
            user_id
        )

        try:

            await call.message.edit_text(
                text,
                reply_markup=kb
            )

        except TelegramBadRequest:

            pass

        await call.answer()

    finally:

        PAGE_LOCK.pop(
            user_id,
            None
        )


# =========================
# PAGE CALLBACKS
# =========================

async def callback_limit(
    user_id
):

    now = time.time()

    last = CALLBACK_COOLDOWN.get(
        user_id,
        0
    )

    if now - last < 0.8:

        return False

    CALLBACK_COOLDOWN[user_id] = now

    return True


@router.callback_query(
    F.data == "next"
)
async def next_page(call):

    uid = call.from_user.id

    if not await callback_limit(uid):

        return await call.answer()

    state = user_states.get(uid)

    if not state:

        return

    max_page = (

        len(state["data"]) - 1

    ) // PAGE_SIZE

    state["page"] = min(

        max_page,

        state["page"] + 1
    )

    await render_page(
        call,
        uid
    )


@router.callback_query(
    F.data == "prev"
)
async def prev_page(call):

    uid = call.from_user.id

    if not await callback_limit(uid):

        return await call.answer()

    state = user_states.get(uid)

    if not state:

        return

    state["page"] = max(

        0,

        state["page"] - 1
    )

    await render_page(
        call,
        uid
    )


@router.callback_query(
    F.data.startswith(
        "page:"
    )
)
async def goto_page(call):

    uid = call.from_user.id

    if not await callback_limit(uid):

        return await call.answer()

    state = user_states.get(uid)

    if not state:

        return

    try:

        page = int(
            call.data.split(":")[1]
        )

    except:

        return await call.answer(
            "Invalid"
        )

    max_page = (

        len(state["data"]) - 1

    ) // PAGE_SIZE

    state["page"] = max(

        0,

        min(
            page,
            max_page
        )
    )

    page_history.setdefault(
        uid,
        set()
    ).add(page)

    await render_page(
        call,
        uid
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
