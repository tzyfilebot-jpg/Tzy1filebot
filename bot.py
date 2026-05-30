# =========================
# IMPORT
# =========================

import os
import secrets
import string
import asyncpg

from dotenv import load_dotenv

from aiogram import Bot, Router, F
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

from aiogram.exceptions import TelegramBadRequest

# =========================
# CONFIG
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

CHANNEL_DB = os.getenv("CHANNEL_DB")
ADMINS = set(int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip().isdigit())

FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")

# =========================
# DB POOL
# =========================

db_pool: asyncpg.Pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)

# =========================
# CACHE
# =========================

upload_sessions = {}
user_states = {}

# =========================
# KEYBOARD
# =========================

def get_keyboard(is_admin: bool = False):
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📤 Up File"),
                KeyboardButton(text="📥 Get File")
            ],
            [
                KeyboardButton(text="👤 Account"),
                KeyboardButton(text="💎 VIP")
            ]
        ],
        resize_keyboard=True
    )

# =========================
# FORCE SUB
# =========================

async def check_force_sub(bot: Bot, user_id: int, channel: str) -> bool:
    try:
        channel = channel.replace("@", "")
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramBadRequest:
        return False

def force_kb(channel: str):
    ch = channel.replace("@", "")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton("📢 Join", url=f"https://t.me/{ch}")],
            [InlineKeyboardButton("🔄 Check", callback_data="check_sub")]
        ]
    )

# =========================
# ROUTER
# =========================

router = Router()

# =========================
# START
# =========================

@router.message(F.text == "/start")
async def start(message: Message, bot: Bot):
    user_id = message.from_user.id

    if not await check_force_sub(bot, user_id, FORCE_CHANNEL):
        await message.answer(
            "⚠ Wajib join channel dulu",
            reply_markup=force_kb(FORCE_CHANNEL)
        )
        return

    await message.answer(
        "🔥 Menu Bot Aktif",
        reply_markup=get_keyboard(user_id in ADMINS)
    )

# =========================
# UP FILE INIT
# =========================

def upload_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("✅ DONE", callback_data="upload_done"),
                InlineKeyboardButton("❌ CANCEL", callback_data="upload_cancel")
            ]
        ]
    )

@router.message(F.text == "📤 Up File")
async def up_file(message: Message):
    user_id = message.from_user.id

    user_states[user_id] = "upload"
    upload_sessions[user_id] = {
        "video": 0,
        "photo": 0,
        "document": 0,
        "items": []
    }

    msg = await message.answer(
        "📤 Upload mode aktif",
        reply_markup=upload_kb()
    )

    upload_sessions[user_id]["msg_id"] = msg.message_id

# =========================
# MEDIA HANDLER
# =========================

@router.message(F.photo | F.video | F.document)
async def handle_media(message: Message):
    user_id = message.from_user.id

    if user_states.get(user_id) != "upload":
        return

    s = upload_sessions[user_id]

    if message.photo:
        s["photo"] += 1
        file = message.photo[-1].file_id
        t = "photo"
        size = message.photo[-1].file_size

    elif message.video:
        s["video"] += 1
        file = message.video.file_id
        t = "video"
        size = message.video.file_size

    else:
        s["document"] += 1
        file = message.document.file_id
        t = "document"
        size = message.document.file_size

    s["items"].append({"file_id": file, "type": t, "size": size})

    text = (
        "📤 Uploading...\n\n"
        f"🎥 {s['video']} | 🖼 {s['photo']} | 📁 {s['document']}\n"
        f"📦 Total: {len(s['items'])}"
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
    rand = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    return f"tzy_{v}v_{p}p_{d}d_{rand}"

# =========================
# DONE
# =========================

@router.callback_query(F.data == "upload_done")
async def done(call: CallbackQuery):
    user_id = call.from_user.id
    s = upload_sessions.get(user_id)

    if not s or not s["items"]:
        await call.answer("kosong")
        return

    code = generate_code(s["video"], s["photo"], s["document"])

    total_size = sum(x["size"] for x in s["items"])

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO codes (code, owner_id, total_media, total_size) VALUES ($1,$2,$3,$4)",
            code, user_id, len(s["items"]), total_size
        )

    upload_sessions.pop(user_id, None)
    user_states.pop(user_id, None)

    await call.message.edit_text(
        f"✅ DONE\n\n<code>{code}</code>",
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

    await call.message.edit_text("❌ Cancelled")
# =========================

# OPEN GET FILE MODE

# =========================

@router.message(F.text == "📥 Get File")

async def get_file_start(message: Message):

    user_id = message.from_user.id

    user_states[user_id] = "getfile"

    await message.answer("📥 Kirim CODE untuk mengambil file")

# =========================

# LOAD DATA FROM DB

# =========================

async def load_media(code: str):

    async with db_pool.acquire() as conn:

        return await conn.fetch(

            "SELECT file_id, file_type FROM medias WHERE code=$1 ORDER BY id ASC",

            code

        )

# =========================

# RECEIVE CODE

# =========================

@router.message(F.text)

async def receive_code(message: Message):

    user_id = message.from_user.id

    if user_states.get(user_id) != "getfile":

        return

    code = message.text.strip()

    data = await load_media(code)

    if not data:

        await message.answer("❌ CODE tidak ditemukan")

        return

    user_states[user_id] = {

        "mode": "view",

        "code": code,

        "index": 0,

        "page": 0,

        "data": data

    }

    await send_page(message, user_id)

# =========================

# BUILD KEYBOARD

# =========================

def build_kb(page, total_pages, show_numbers=True):

    nav = []

    # prev

    nav.append({"text": "⬅ Prev", "callback_data": "prev"})

    # page numbers (only if many pages)

    if show_numbers:

        for i in range(total_pages):

            nav.append({"text": str(i + 1), "callback_data": f"page:{i}"})

    # next

    nav.append({"text": "Next ➡", "callback_data": "next"})

    return InlineKeyboardMarkup(

        inline_keyboard=[

            nav,

            [

                {"text": "📢 Channel Update", "url": "https://t.me/" + UPDATE_CHANNEL.replace("@", "")},

                {"text": "🔔 Notification", "url": "https://t.me/" + NOTIFICATION_CHANNEL.replace("@", "")}

            ]

        ]

    )

# =========================

# SEND PAGE (MAX 5 MEDIA PER BUBBLE)

# =========================

async def send_page(message: Message, user_id: int):

    state = user_states[user_id]

    data = state["data"]

    page_size = 5

    page = state["page"]

    start = page * page_size

    end = start + page_size

    chunk = data[start:end]

    total_pages = (len(data) + page_size - 1) // page_size

    show_numbers = len(data) > 5

    text = (

        f"📦 CODE: {state['code']}\n"

        f"📄 Page {page+1}/{total_pages}\n"

        f"🔒 WATERMARK: @YourBotName"

    )

    # kalau hanya 1 file di page → kirim normal

    if len(chunk) == 1:

        m = chunk[0]

        await send_single(message, m, text, page, total_pages, show_numbers)

        return

    # kalau 2-5 file → album style (bubble group logic simplified)

    media_group = []

    for m in chunk:

        if m["file_type"] == "photo":

            media_group.append(InputMediaPhoto(media=m["file_id"]))

        elif m["file_type"] == "video":

            media_group.append(InputMediaVideo(media=m["file_id"]))

        else:

            media_group.append(InputMediaDocument(media=m["file_id"]))

    await message.answer_media_group(media_group)

    await message.answer(

        text,

        reply_markup=build_kb(page, total_pages, show_numbers)

    )

# =========================

# SINGLE MEDIA VIEW

# =========================

async def send_single(message, m, text, page, total_pages, show_numbers):

    kb = build_kb(page, total_pages, show_numbers)

    if m["file_type"] == "photo":

        await message.answer_photo(m["file_id"], caption=text, reply_markup=kb)

    elif m["file_type"] == "video":

        await message.answer_video(m["file_id"], caption=text, reply_markup=kb)

    else:

        await message.answer_document(m["file_id"], caption=text, reply_markup=kb)

# =========================

# PAGINATION CONTROL

# =========================

@router.callback_query(F.data.in_(["next", "prev"]))

async def paginate(call: CallbackQuery):

    user_id = call.from_user.id

    if user_id not in user_states:

        return

    state = user_states[user_id]

    if state.get("mode") != "view":

        return

    total_pages = (len(state["data"]) + 4) // 5

    if call.data == "next":

        if state["page"] < total_pages - 1:

            state["page"] += 1

    elif call.data == "prev":

        if state["page"] > 0:

            state["page"] -= 1

    await call.message.delete()

    await send_page(call.message, user_id)

# =========================

# PAGE SELECT (1 2 3 4 5)

# =========================

@router.callback_query(F.data.startswith("page:"))

async def select_page(call: CallbackQuery):

    user_id = call.from_user.id

    if user_id not in user_states:

        return

    page = int(call.data.split(":")[1])

    state = user_states[user_id]

    state["page"] = page

    await call.message.delete()

    await send_page(call.message, user_id)

# =========================
# HELP
# =========================

@router.message(F.text == "/help")
async def help_cmd(message: Message):
    await message.answer(
        "📖 HELP MENU\n\n"
        "📤 Up File → upload media & generate code\n"
        "📥 Get File → ambil file pakai code\n"
        "👤 Account → lihat akun kamu\n"
        "💎 VIP → fitur premium\n"
    )

# =========================
# ACCOUNT
# =========================

@router.message(F.text == "👤 Account")
async def account_cmd(message: Message):
    user = message.from_user

    await add_user(
        user.id,
        user.username or "none",
        user.full_name
    )

    await message.answer(
        "👤 ACCOUNT INFO\n\n"
        f"🆔 ID: {user.id}\n"
        f"👤 Name: {user.full_name}\n"
        f"🔗 Username: @{user.username if user.username else 'none'}"
    )

# =========================
# VIP
# =========================

def vip_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Join VIP",
                    url=f"https://t.me/{VIP_LINK}"
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
        "🔥 Fast Response\n",
        reply_markup=vip_kb()
    )


@router.callback_query(F.data == "vip_cancel")
async def vip_cancel(call: CallbackQuery):
    await call.message.edit_text("❌ VIP dibatalkan")

# =========================
# ADMIN PANEL
# =========================

def is_admin(user_id: int):
    return user_id in ADMINS

# =========================
# ADD ADMIN
# =========================

@router.message(F.text.startswith("/addadmin"))
async def add_admin(message: Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("❌ Not allowed")

    try:
        uid = int(message.text.split()[1])
        ADMINS.add(uid)
        await message.answer(f"✅ Admin ditambah: {uid}")
    except:
        await message.answer("❌ Format: /addadmin <id>")

# =========================
# STATISTIC
# =========================

@router.message(F.text == "/stat")
async def stat_cmd(message: Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("❌ Not allowed")

    users = await db_pool.fetchval("SELECT COUNT(*) FROM users")
    codes = await db_pool.fetchval("SELECT COUNT(*) FROM codes")
    media = await db_pool.fetchval("SELECT COUNT(*) FROM medias")

    await message.answer(
        "📊 STATISTIC\n\n"
        f"👤 Users: {users}\n"
        f"🔑 Codes: {codes}\n"
        f"📦 Media: {media}"
    )

# =========================
# BROADCAST
# =========================

@router.message(F.text.startswith("/broadcast"))
async def broadcast_cmd(message: Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("❌ Not allowed")

    text = message.text.replace("/broadcast", "").strip()

    if not text:
        return await message.answer("❌ /broadcast pesan")

    users = await db_pool.fetch("SELECT user_id FROM users")

    for u in users:
        try:
            await message.bot.send_message(u["user_id"], text)
        except:
            pass

    await message.answer("✅ Broadcast selesai")

# =========================
# STARTUP
# =========================

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(router)

    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
