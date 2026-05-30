# =========================
# IMPORT
# =========================

import os
import secrets
import string
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
        max_size=10
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

upload_sessions = {}
user_states = {}

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
        file_id = message.photo[-1].file_id
        file_type = "photo"
        size = message.photo[-1].file_size

    elif message.video:

        s["video"] += 1
        file_id = message.video.file_id
        file_type = "video"
        size = message.video.file_size

    else:

        s["document"] += 1
        file_id = message.document.file_id
        file_type = "document"
        size = message.document.file_size

    s["items"].append({
        "file_id": file_id,
        "type": file_type,
        "size": size
    })

    text = (
        "📤 Uploading...\n\n"
        f"🎥 {s['video']} | "
        f"🖼 {s['photo']} | "
        f"📁 {s['document']}\n"
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

@router.callback_query(
    F.data == "upload_done"
)
async def done(call: CallbackQuery):

    user_id = call.from_user.id

    s = upload_sessions.get(user_id)

    if not s or not s["items"]:

        await call.answer(
            "kosong"
        )

        return

    code = generate_code(
        s["video"],
        s["photo"],
        s["document"]
    )

    total_size = sum(
        x["size"]
        for x in s["items"]
    )

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

            VALUES
            (
                $1,
                $2,
                $3,
                $4
            )
            """,
            code,
            user_id,
            len(s["items"]),
            total_size
        )

        for media in s["items"]:

            await conn.execute(
                """
                INSERT INTO medias
                (
                    code,
                    file_id,
                    file_type,
                    file_size
                )

                VALUES
                (
                    $1,
                    $2,
                    $3,
                    $4
                )
                """,
                code,
                media["file_id"],
                media["type"],
                media["size"]
            )

    upload_sessions.pop(
        user_id,
        None
    )

    user_states.pop(
        user_id,
        None
    )

    await call.message.edit_text(
        f"✅ DONE\n\n"
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
            SELECT file_id, file_type
            FROM medias
            WHERE code=$1
            ORDER BY id ASC
            """,
            code
        )

# =========================
# RECEIVE CODE
# =========================

@router.message(F.text)
async def receive_code(message: Message):

    user_id = message.from_user.id

    state = user_states.get(user_id)

    if not state:
        return

    if state.get("mode") != "getfile":
        return

    code = message.text.strip()

    data = await load_media(code)

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
                    text="📢 Update",
                    url=f"https://t.me/{UPDATE_CHANNEL.replace('@','')}"
                ),

                InlineKeyboardButton(
                    text="🔔 Notification",
                    url=f"https://t.me/{NOTIFICATION_CHANNEL.replace('@','')}"
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
        f"📄 Page {page+1}/{total_pages}\n"
        f"🔒 WATERMARK: @YourBotName"

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

    for user in users:

        try:

            await message.bot.send_message(
                user["user_id"],
                text
            )

            sent += 1

        except:

            pass

    await message.answer(
        f"✅ Broadcast selesai\n\n"
        f"📤 Terkirim: {sent}"
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

        await bot.session.close()

# =========================
# RUN
# =========================

if __name__ == "__main__":

    import asyncio

    asyncio.run(
        main()
    )
