import os
import asyncio
import secrets
import time
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
    InputMediaDocument,
)
from aiogram.exceptions import TelegramBadRequest

# =========================
# LOAD ENV
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

CHANNEL_DB = os.getenv("CHANNEL_DB")
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL")
VIP_LINK = os.getenv("VIP_LINK")

ADMINS = {int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip().isdigit()}

# =========================
# INIT
# =========================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()

db_pool = None

MAX_UPLOAD = 10

upload_sessions = {}
user_mode = {}
last_edit = {}

# =========================
# SAVAGE TEXTS
# =========================

SAVAGE = {
    "done_success": [
        "😏 Udah selesai? yaudah gue simpen. jangan hilangin code terus nangis ya.",
        "💀 File aman. yang gak aman itu kamu kalau lupa code sendiri.",
        "🔥 Beres. tapi jangan balik lagi nanya hal yang sama ya.",
    ],
    "limit": "🚫 Limit 10 file. ini bukan storage cloud unlimited gratisan.",
    "empty": "😏 Kosong tapi pencet done? kamu bercanda atau gimana?",
    "invalid": "💀 Code gak valid. mungkin kamu yang salah, bukan sistem."
}

# =========================
# DB INIT FIX (ANTI PGBOUNCER ERROR)
# =========================

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        statement_cache_size=0,
        command_timeout=60
    )

    async with db_pool.acquire() as c:
        await c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            fullname TEXT
        );

        CREATE TABLE IF NOT EXISTS codes(
            code TEXT PRIMARY KEY,
            owner BIGINT,
            total INT,
            size BIGINT
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
# UTIL
# =========================

def gen_code():
    return "CODE_" + secrets.token_hex(4)

async def check_join(bot, uid):
    try:
        m = await bot.get_chat_member(FORCE_CHANNEL, uid)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

# =========================
# KEYBOARD
# =========================

def menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Up File"), KeyboardButton(text="📥 Get File")],
            [KeyboardButton(text="👤 Account"), KeyboardButton(text="❓ Help")]
        ],
        resize_keyboard=True
    )

def upload_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Done", callback_data="done"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")
        ]
    ])

# =========================
# SAVE USER
# =========================

async def save_user(uid, username, fullname):
    async with db_pool.acquire() as c:
        await c.execute("""
        INSERT INTO users VALUES($1,$2,$3)
        ON CONFLICT(user_id) DO UPDATE
        SET username=$2, fullname=$3
        """, uid, username, fullname)

# =========================
# START
# =========================

@router.message(F.text == "/start")
async def start(m: Message):
    u = m.from_user

    await save_user(u.id, u.username or "none", u.full_name)

    if FORCE_CHANNEL and not await check_join(m.bot, u.id):
        return await m.answer(
            "⚠️ LOH BELUM JOIN CHANNEL.\n"
            "Join dulu baru boleh pake bot.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="JOIN CHANNEL", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")],
                [InlineKeyboardButton(text="CHECK", callback_data="check")]
            ])
        )

    await m.answer(
        "🔥 MENU ACTIVE\n"
        "💀 Jangan salah pake bot ya, nanti kamu sendiri yang bingung.",
        reply_markup=menu()
    )

# =========================
# CHECK JOIN
# =========================

@router.callback_query(F.data == "check")
async def check(c: CallbackQuery):
    if await check_join(c.bot, c.from_user.id):
        await c.message.edit_text("✅ VERIFIED")
        await c.message.answer("🔥 MENU READY", reply_markup=menu())
    else:
        await c.answer("❌ BELUM JOIN", show_alert=True)

# =========================
# UPLOAD MODE
# =========================

@router.message(F.text == "📤 Up File")
async def up(m: Message):
    uid = m.from_user.id

    upload_sessions[uid] = {
        "items": [],
        "size": 0,
        "chat": m.chat.id,
        "msg_id": None
    }

    user_mode[uid] = "upload"

    msg = await m.answer(
        "📤 UPLOAD MODE AKTIF\n"
        "💀 Maks 10 file. jangan lebay upload terus.",
        reply_markup=upload_kb()
    )

    upload_sessions[uid]["msg_id"] = msg.message_id

# =========================
# MEDIA HANDLER
# =========================

@router.message(F.photo | F.video | F.document)
async def media(m: Message):
    uid = m.from_user.id

    if user_mode.get(uid) != "upload":
        return

    s = upload_sessions.get(uid)
    if not s:
        return

    if len(s["items"]) >= MAX_UPLOAD:
        return await m.answer(SAVAGE["limit"])

    if m.photo:
        f, t = m.photo[-1], "photo"
    elif m.video:
        f, t = m.video, "video"
    else:
        f, t = m.document, "doc"

    s["items"].append({
        "file_id": f.file_id,
        "type": t,
        "size": f.file_size or 0
    })

    s["size"] += f.file_size or 0

    try:
        await m.bot.edit_message_text(
            chat_id=s["chat"],
            message_id=s["msg_id"],
            text=f"📦 UPLOAD: {len(s['items'])}/{MAX_UPLOAD}",
            reply_markup=upload_kb()
        )
    except TelegramBadRequest:
        pass

# =========================
# DONE
# =========================

@router.callback_query(F.data == "done")
async def done(c: CallbackQuery):
    uid = c.from_user.id
    s = upload_sessions.get(uid)

    if not s or not s["items"]:
        return await c.answer(SAVAGE["empty"], show_alert=True)

    code = gen_code()

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO codes VALUES($1,$2,$3,$4)",
            code, uid, len(s["items"]), s["size"]
        )

        for i in s["items"]:
            await conn.execute(
                "INSERT INTO medias(code,file_id,file_type,file_size) VALUES($1,$2,$3,$4)",
                code, i["file_id"], i["type"], i["size"]
            )

    upload_sessions.pop(uid, None)
    user_mode.pop(uid, None)

    await c.message.edit_text(
        f"🔥 UPLOAD DONE\n\n"
        f"CODE: <code>{code}</code>\n"
        f"TOTAL: {len(s['items'])}\n"
        f"SIZE: {round(s['size']/1024/1024,2)} MB\n\n"
        f"{secrets.choice(SAVAGE['done_success'])}",
        parse_mode="HTML"
    )

# =========================
# CANCEL
# =========================

@router.callback_query(F.data == "cancel")
async def cancel(c: CallbackQuery):
    upload_sessions.pop(c.from_user.id, None)
    user_mode.pop(c.from_user.id, None)
    await c.message.edit_text("❌ CANCELLED. yaudah santai aja.")

# =========================
# GET MODE
# =========================

@router.message(F.text == "📥 Get File")
async def get_mode(m: Message):
    user_mode[m.from_user.id] = "get"
    await m.answer("📥 KIRIM CODE SEKARANG")

# =========================
# GET FILE (FIXED SAFE)
# =========================

@router.message(F.text & ~F.command)
async def get_file(m: Message):
    uid = m.from_user.id

    if user_mode.get(uid) != "get":
        return

    code = m.text.strip()

    async with db_pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM medias WHERE code=$1", code)

    if not rows:
        return await m.answer(SAVAGE["invalid"])

    media = []

    for r in rows[:10]:
        if r["file_type"] == "photo":
            media.append(InputMediaPhoto(r["file_id"]))
        elif r["file_type"] == "video":
            media.append(InputMediaVideo(r["file_id"]))
        else:
            media.append(InputMediaDocument(r["file_id"]))

    await m.bot.send_media_group(m.chat.id, media)

    await m.answer(
        f"🔓 CODE: {code}\n"
        "😏 Udah kebuka, jangan disalahgunakan ya.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 UPDATE", url=f"https://t.me/{UPDATE_CHANNEL.replace('@','')}")]
        ])
    )

# =========================
# ACCOUNT
# =========================

@router.message(F.text == "👤 Account")
async def account(m: Message):
    async with db_pool.acquire() as c:
        codes = await c.fetch("SELECT code FROM codes WHERE owner=$1", m.from_user.id)

    txt = "\n".join([x["code"] for x in codes]) or "EMPTY"
    await m.answer(f"👤 ACCOUNT\n\n{txt}")

# =========================
# HELP
# =========================

@router.message(F.text == "❓ Help")
async def help(m: Message):
    await m.answer(
        "📤 UP → upload → done\n"
        "📥 GET → kirim code\n"
        "💀 jangan abuse bot"
    )

# =========================
# MAIN
# =========================

async def main():
    await init_db()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
