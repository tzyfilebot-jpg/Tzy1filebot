import asyncio
import time
import secrets

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart

from config import BOT_TOKEN, OWNER_ID, UPDATE_CHANNEL, NOTIF_CHANNEL, DB_CHANNEL_ID
from database import (
    add_user,
    is_admin,
    create_upload,
    add_media,
    get_media
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# STATE
# =========================

upload_session = {}
cooldown = {}

# =========================
# KEYBOARD
# =========================

def user_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Up File", callback_data="upload"),
            InlineKeyboardButton(text="📥 Get File", callback_data="getfile")
        ],
        [
            InlineKeyboardButton(text="❓ Help", callback_data="help"),
            InlineKeyboardButton(text="👤 Account", callback_data="account")
        ],
        [
            InlineKeyboardButton(text="💎 VIP", callback_data="vip")
        ]
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Up File", callback_data="upload"),
            InlineKeyboardButton(text="📥 Get File", callback_data="getfile")
        ],
        [
            InlineKeyboardButton(text="❓ Help", callback_data="help"),
            InlineKeyboardButton(text="👤 Account", callback_data="account")
        ],
        [
            InlineKeyboardButton(text="📊 Stats", callback_data="stats"),
            InlineKeyboardButton(text="📢 Broadcast", callback_data="broadcast")
        ]
    ])

# =========================
# FORCE JOIN
# =========================

async def check_join(user_id: int):
    try:
        c1 = await bot.get_chat_member(UPDATE_CHANNEL, user_id)
        c2 = await bot.get_chat_member(NOTIF_CHANNEL, user_id)

        valid = {"member", "administrator", "creator"}
        return c1.status in valid and c2.status in valid
    except:
        return False

# =========================
# START (SAVAGE STYLE)
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    user = message.from_user

    add_user(user.id, user.username, user.first_name)

    if not await check_join(user.id):
        return await message.answer(
            "⛓ Akses ditahan.\n"
            "Kamu belum masuk ke jalur yang benar."
        )

    text = (
        "☠️ SYSTEM ACTIVE\n\n"
        "File tidak disimpan untuk semua orang.\n"
        "Hanya yang paham yang bisa ambil kembali.\n\n"
        "🔑 Code = akses hidupmu di sini.\n"
        "Hilang code = hilang semuanya."
    )

    if user.id == OWNER_ID or is_admin(user.id):
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=user_menu())

# =========================
# HELP / ACCOUNT / VIP
# =========================

@dp.callback_query(F.data == "help")
async def help_cmd(call: CallbackQuery):
    await call.message.answer(
        "📌 Cara kerja:\n\n"
        "1. Upload file\n"
        "2. Bot buat code\n"
        "3. Get file pakai code\n\n"
        "Tidak ada tombol balik kalau salah."
    )


@dp.callback_query(F.data == "account")
async def account(call: CallbackQuery):
    u = call.from_user
    await call.message.answer(
        f"👤 Identity\n\n"
        f"ID: {u.id}\n"
        f"USER: @{u.username or '-'}"
    )


@dp.callback_query(F.data == "vip")
async def vip(call: CallbackQuery):
    await call.message.answer("💎 VIP belum dibuka.")

# =========================
# UPLOAD START
# =========================

@dp.callback_query(F.data == "upload")
async def upload_start(call: CallbackQuery):
    uid = call.from_user.id

    code = "tzy_" + secrets.token_hex(3)

    upload_session[uid] = {
        "code": code,
        "video": 0,
        "photo": 0,
        "doc": 0
    }

    await call.message.answer(
        "📤 Upload aktif.\n\n"
        "Kirim file sekarang.\n"
        "DONE = simpan\nCANCEL = batal"
    )

# =========================
# HANDLE MEDIA
# =========================

@dp.message(F.content_type.in_({"video", "photo", "document"}))
async def handle_media(message: Message):

    uid = message.from_user.id

    if uid not in upload_session:
        return

    session = upload_session[uid]

    msg = await bot.copy_message(
        chat_id=DB_CHANNEL_ID,
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )

    t = message.content_type

    if t == "video":
        session["video"] += 1
    elif t == "photo":
        session["photo"] += 1
    elif t == "document":
        session["doc"] += 1

    add_media(
        session["code"],
        msg.message_id,
        t,
        None,
        0
    )

    await message.answer(
        f"📦 SAVED\n"
        f"🎬 {session['video']} | 🖼 {session['photo']} | 📄 {session['doc']}"
    )

# =========================
# DONE
# =========================

@dp.message(F.text == "DONE")
async def done(message: Message):

    uid = message.from_user.id

    if uid not in upload_session:
        return

    s = upload_session[uid]

    final_code = f"{s['code']}_{s['video']}v_{s['photo']}p_{s['doc']}d"

    create_upload(
        final_code,
        uid,
        s['video'] + s['photo'] + s['doc'],
        0
    )

    del upload_session[uid]

    await message.answer(
        "☠️ FILE LOCKED\n\n"
        f"🔑 {final_code}\n\n"
        "Jangan hilang. Tidak ada backup."
    )

# =========================
# CANCEL
# =========================

@dp.message(F.text == "CANCEL")
async def cancel(message: Message):
    uid = message.from_user.id

    if uid in upload_session:
        del upload_session[uid]

    await message.answer("⚰️ dibatalkan.")

# =========================
# GET FILE SYSTEM
# =========================

@dp.message(F.text)
async def get_file(message: Message):

    text = message.text.strip()

    if not text.startswith("tzy_"):
        return

    code = text

    now = time.time()

    if code in cooldown and now - cooldown[code] < 5:
        return await message.answer("⏳ cooldown")

    cooldown[code] = now

    media = get_media(code)

    if not media:
        return await message.answer("❌ code tidak valid")

    per_page = 5
    pages = [media[i:i+per_page] for i in range(0, len(media), per_page)]

    await message.answer(
        "📥 ACCESS GRANTED\n"
        "Mengambil file..."
    )

    for i, page in enumerate(pages):
        for m in page:
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=DB_CHANNEL_ID,
                message_id=m["message_id"]
            )

        await message.answer(f"PAGE {i+1}/{len(pages)}")

# =========================
# RUN
# =========================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
