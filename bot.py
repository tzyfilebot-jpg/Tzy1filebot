# =========================
# IMPORT
# =========================

import os
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

db_pool: asyncpg.Pool = None

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

        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS fullname TEXT;

        """)
# =========================
# CACHE
# =========================

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

def get_keyboard(is_admin=False):

    rows = [

        [
            KeyboardButton(text="📤 Up File"),
            KeyboardButton(text="📥 Get File")
        ],

        [
            KeyboardButton(text="👤 Account"),
            KeyboardButton(text="💎 VIP")
        ],

        [
            KeyboardButton(text="❓ Help")
        ]

    ]

    return ReplyKeyboardMarkup(

        keyboard=rows,

        resize_keyboard=True,

        input_field_placeholder="Pilih menu..."

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

    except TelegramBadRequest:

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
async def start(
    message: Message,
    bot: Bot
):

    user = message.from_user

    await add_user(
        user.id,
        user.username or "none",
        user.full_name
    )

    # kalau force sub dimatikan
    if not FORCE_CHANNEL:

        return await message.answer(
            "🔥 Menu aktif",
            reply_markup=get_keyboard(
                is_admin(user.id)
            )
        )

    # cek join channel
    ok = await check_force_sub(
        bot,
        user.id,
        FORCE_CHANNEL
    )

    if not ok:

        return await message.answer(
            "⚠️ Join channel dulu sebelum pakai bot",
            reply_markup=force_kb(
                FORCE_CHANNEL
            )
        )

    await message.answer(
        "🔥 Menu aktif",
        reply_markup=get_keyboard(
            is_admin(
                user.id
            )
        )
    )


# =========================
# CHECK SUB
# =========================

@router.callback_query(
    F.data == "check_sub"
)
async def check_sub(
    call: CallbackQuery,
    bot: Bot
):

    # force sub OFF
    if not FORCE_CHANNEL:

        return await call.answer(
            "Force sub OFF",
            show_alert=True
        )

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

    await call.message.edit_text(
        "✅ Verified"
    )

    await call.message.answer(
        "🔥 Menu aktif",
        reply_markup=get_keyboard(
            is_admin(
                call.from_user.id
            )
        )
    )
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

    if not state or state.get("mode") != "upload":
        return

    if not s or not s.get("msg_id"):
        return

    # AMBIL FILE
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
        size = message.photo[-1].file_size or 0
        s["photo"] += 1

    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
        size = message.video.file_size or 0
        s["video"] += 1

    else:
        file_id = message.document.file_id
        file_type = "document"
        size = message.document.file_size or 0
        s["document"] += 1

    s["items"].append({
        "file_id": file_id,
        "type": file_type,
        "size": size
    })

    # 💀 auto delete user spam
    try:
        await message.delete()
    except:
        pass

    # 🧠 anti flood ringan
    now = time.time()
    last = last_edit_time.get(user_id, 0)

    if now - last < 0.9:
        return

    last_edit_time[user_id] = now

    total = len(s["items"])
    size_mb = round(sum(x["size"] for x in s["items"]) / (1024 * 1024), 2)

    # 💀 SAVAGE TEXT UI
    text = (
        "📤 UPLOADING...\n\n"
        f"🎥 Video     : {s['video']}\n"
        f"🖼 Photo     : {s['photo']}\n"
        f"📁 Document  : {s['document']}\n"
        f"📦 Total     : {total}\n"
        f"💾 Size      : {size_mb} MB\n\n"
        "😏 Bot bekerja...\n"
        "💀 Jangan cuma nonton, kirim semua file kamu."
    )

    try:
        await message.bot.edit_message_text(
            chat_id=user_id,
            message_id=s["msg_id"],
            text=text,
            reply_markup=upload_kb()
        )
    except:
        pass
# =========================
# GENERATE CODE
# =========================

def generate_code(v, p, d):

    rand = "".join(

        secrets.choice(
            string.ascii_lowercase +
            string.digits
        )

        for _ in range(10)

    )

    return f"tzy_{v}v_{p}p_{d}d_{rand}"

# =========================
# DONE
# =========================

@router.callback_query(F.data == "upload_done")
async def done(call: CallbackQuery):

    user_id = call.from_user.id
    s = upload_sessions.get(user_id)

    if not s or not s["items"]:
        return await call.answer(
            "😏 kosong? ya jelas gak ada yang diproses",
            show_alert=True
        )

    code = generate_code(
        s["video"],
        s["photo"],
        s["document"]
    )

    total_size = sum(x["size"] for x in s["items"])

    async with db_pool.acquire() as conn:

        await conn.execute(
            """
            INSERT INTO codes(code, owner_id, total_media, total_size)
            VALUES($1,$2,$3,$4)
            """,
            code,
            user_id,
            len(s["items"]),
            total_size
        )

        await conn.executemany(
            """
            INSERT INTO medias(code, file_id, file_type, file_size)
            VALUES($1,$2,$3,$4)
            """,
            [
                (code, m["file_id"], m["type"], m["size"])
                for m in s["items"]
            ]
        )

    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)
    last_edit_time.pop(user_id, None)

    await call.message.edit_text(
        "💀 UPLOAD COMPLETE\n\n"
        f"😏 CODE: <code>{code}</code>\n\n"
        "📌 Simpan CODE itu baik-baik\n"
        "Kalau hilang...\n"
        "itu bukan salah bot ya 😌",
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
        "📥 Kirim CODE untuk mengambil file"
    )

# =========================
# LOAD DATA FROM DB
# =========================

async def load_media(code: str):

    async with db_pool.acquire() as conn:

        return await conn.fetch(
            """
            SELECT
                file_id,
                file_type,
                file_size

            FROM medias

            WHERE code=$1

            ORDER BY id ASC
            """,
            code
        )
# =========================
# RECEIVE CODE
# =========================

@router.message(
    F.text &
    ~F.text.startswith("/") &
    ~F.text.in_([
        "📤 Up File",
        "📥 Get File",
        "👤 Account",
        "💎 VIP",
        "❓ Help"
    ])
)
async def receive_code(
    message: Message
):

    user_id = message.from_user.id

    state = user_states.get(
        user_id
    )

    if not state:

        return

    if state.get("mode") != "getfile":

        return

    code = message.text.strip()

    data = await load_media(
        code
    )

    if not data:

        await message.answer(
            "❌ CODE tidak ditemukan"
        )

        return

    user_states[user_id] = {

        "mode": "view",
        "code": code,
        "page": 0,
        "data": data

    }

    await send_page(
        message,
        user_id
    )
# =========================
# BUILD KEYBOARD
# =========================

def build_kb(
    page,
    total_pages,
    show_numbers=True
):

    nav = []

    nav.append(
        InlineKeyboardButton(
            text="⬅ Prev",
            callback_data="prev"
        )
    )

    if show_numbers:

        for i in range(total_pages):

            nav.append(
                InlineKeyboardButton(
                    text=str(i + 1),
                    callback_data=f"page:{i}"
                )
            )

    nav.append(
        InlineKeyboardButton(
            text="Next ➡",
            callback_data="next"
        )
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
# =========================
# SEND PAGE
# =========================

async def send_page(
    message: Message,
    user_id: int
):

    state = user_states[user_id]

    data = state["data"]

    page_size = 5

    page = state["page"]

    start = page * page_size
    end = start + page_size

    chunk = data[start:end]

    total_pages = (
        len(data) + page_size - 1
    ) // page_size

    show_numbers = total_pages > 1

    text = (

    f"📦 CODE: {state['code']}\n"

    f"📄 Halaman saat ini: {page+1}/{total_pages}\n"

    f"📁 Media: {current_media}-{min(end,total_media)} / {total_media}\n"

    f"💾 Total Size: {size_mb} MB\n"

    f"🔒 Powered By TZY FILE BOT"

)

    if len(chunk) == 1:

        media = chunk[0]

        await send_single(
            message,
            media,
            text,
            page,
            total_pages,
            show_numbers
        )

        return

    media_group = []

    for media in chunk:

        if media["file_type"] == "photo":

            media_group.append(
                InputMediaPhoto(
                    media=media["file_id"]
                )
            )

        elif media["file_type"] == "video":

            media_group.append(
                InputMediaVideo(
                    media=media["file_id"]
                )
            )

        else:

            media_group.append(
                InputMediaDocument(
                    media=media["file_id"]
                )
            )

    await message.answer_media_group(
        media_group
    )

    await message.answer(
        text,
        reply_markup=build_kb(
            page,
            total_pages,
            show_numbers
        )
    )

# =========================
# SEND SINGLE
# =========================

async def send_single(
    message,
    media,
    text,
    page,
    total_pages,
    show_numbers
):

    kb = build_kb(
        page,
        total_pages,
        show_numbers
    )

    if media["file_type"] == "photo":

        await message.answer_photo(
            media["file_id"],
            caption=text,
            reply_markup=kb
        )

    elif media["file_type"] == "video":

        await message.answer_video(
            media["file_id"],
            caption=text,
            reply_markup=kb
        )

    else:

        await message.answer_document(
            media["file_id"],
            caption=text,
            reply_markup=kb
        )

# =========================
# PAGINATION
# =========================

@router.callback_query(
    F.data.in_(["next", "prev"])
)
async def paginate(
    call: CallbackQuery
):

    user_id = call.from_user.id

    state = user_states.get(user_id)

    if not state:
        return

    if state.get("mode") != "view":
        return

    total_pages = (
        len(state["data"]) + 4
    ) // 5

    if call.data == "next":

        if state["page"] < total_pages - 1:
            state["page"] += 1

    else:

        if state["page"] > 0:
            state["page"] -= 1

    await call.message.delete()

    await send_page(
        call.message,
        user_id
    )

# =========================
# PAGE SELECT
# =========================

@router.callback_query(
    F.data.startswith("page:")
)
async def select_page(
    call: CallbackQuery
):

    user_id = call.from_user.id

    state = user_states.get(user_id)

    if not state:
        return

    page = int(
        call.data.split(":")[1]
    )

    state["page"] = page

    await call.message.delete()

    await send_page(
        call.message,
        user_id
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

@router.message(
    F.text == "👤 Account"
)
async def account_cmd(
    message: Message
):

    user = message.from_user

    await add_user(
        user.id,
        user.username or "none",
        user.full_name
    )

    await message.answer(

        f"👤 ACCOUNT INFO\n\n"
        f"🆔 ID: {user.id}\n"
        f"👤 Name: {user.full_name}\n"
        f"🔗 Username: @{user.username or 'none'}"

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
                    text="🚀 Join VIP",
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


@router.message(F.text == "💎 VIP")
async def vip_menu(message: Message):

    await message.answer(
        "💎 VIP MENU\n\n"
        "🔥 Unlimited Upload\n"
        "🔥 Priority Get File\n"
        "🔥 Fast Response",
        reply_markup=vip_kb()
    )


@router.callback_query(
    F.data == "vip_cancel"
)
async def vip_cancel(
    call: CallbackQuery
):

    await call.message.edit_text(
        "❌ VIP dibatalkan"
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

@router.message(
    F.text.startswith("/addadmin")
)
async def add_admin(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        return await message.answer(
            "❌ Not allowed"
        )

    try:

        uid = int(
            message.text.split()[1]
        )

        ADMINS.add(uid)

        await message.answer(
            f"✅ Admin ditambah: {uid}"
        )

    except:

        await message.answer(
            "❌ Format:\n/addadmin <id>"
        )

# =========================
# STATISTIC
# =========================

@router.message(
    F.text == "/stat"
)
async def stat_cmd(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        return await message.answer(
            "❌ Not allowed"
        )

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

    await message.answer(

        "📊 STATISTIC\n\n"
        f"👤 Users: {users}\n"
        f"🔑 Codes: {codes}\n"
        f"📦 Media: {media}"

    )

# =========================
# BROADCAST
# =========================

import asyncio

@router.message(
    F.text.startswith("/broadcast")
)
async def broadcast_cmd(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        return await message.answer(
            "❌ Not allowed"
        )

    text = (
        message.text
        .replace("/broadcast", "")
        .strip()
    )

    if not text:

        return await message.answer(
            "❌ Format:\n/broadcast pesan"
        )

    async with db_pool.acquire() as conn:

        users = await conn.fetch(
            """
            SELECT user_id
            FROM users
            """
        )

    sent = 0
    failed = 0

    for user in users:

        try:

            await message.bot.send_message(
                user["user_id"],
                text
            )

            sent += 1

            await asyncio.sleep(
                0.05
            )

        except Exception:

            failed += 1

            pass

    await message.answer(

        f"✅ Broadcast selesai\n\n"
        f"📤 Terkirim: {sent}\n"
        f"❌ Gagal: {failed}"

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
