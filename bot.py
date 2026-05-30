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
user_page = {}
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
        "doc": 0,
        "active": True
    }

    await call.message.edit_text(
        "📤 UPLOAD MODE AKTIF\n\n"
        "Kirim media sekarang.\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ DONE", callback_data="done_upload"),
                InlineKeyboardButton(text="❌ CANCEL", callback_data="cancel_upload")
            ]
        ])
    )

# =========================
# HANDLE MEDIA (NO SPAM)
# =========================

@dp.message(F.content_type.in_({"video", "photo", "document"}))
async def handle_media(message: Message):

    uid = message.from_user.id

    if uid not in upload_session:
        return

    if not upload_session[uid].get("active"):
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

# =========================
# DONE UPLOAD
# =========================

@dp.callback_query(F.data == "done_upload")
async def done_upload(call: CallbackQuery):

    uid = call.from_user.id

    if uid not in upload_session:
        return

    s = upload_session[uid]
    s["active"] = False

    final_code = f"{s['code']}_{s['video']}v_{s['photo']}p_{s['doc']}d"

    create_upload(
        final_code,
        uid,
        s['video'] + s['photo'] + s['doc'],
        0
    )

    del upload_session[uid]

    await call.message.edit_text(
        "☠️ UPLOAD LOCKED\n\n"
        f"🔑 CODE:\n{final_code}\n\n"
        "Simpan baik-baik."
    )

# =========================
# CANCEL UPLOAD
# =========================

@dp.callback_query(F.data == "cancel_upload")
async def cancel_upload(call: CallbackQuery):

    uid = call.from_user.id

    if uid in upload_session:
        del upload_session[uid]

    await call.message.edit_text("⚰️ Upload dibatalkan.")

# =========================
# GET FILE SYSTEM
# =========================

@dp.message()
async def get_file(message: Message):

    text = message.text
    if not text:
        return

    text = text.strip()

    if not text.startswith("tzy_"):
        return

    code = text

    now = time.time()

    if code in cooldown and now - cooldown[code] < 5:
        return await message.answer("⏳ cooldown 5 detik")

    cooldown[code] = now

    media = get_media(code)

    if not media:
        return await message.answer("❌ code tidak valid")

    per_page = 5
    pages = [media[i:i+per_page] for i in range(0, len(media), per_page)]

    user_page[message.from_user.id] = {
        "pages": pages,
        "index": 0
    }

    await message.answer("📥 ACCESS GRANTED")

    await send_page(message, message.from_user.id)

# =========================
# SEND PAGE
# =========================

async def send_page(message, uid):

    session = user_page.get(uid)
    if not session:
        return

    pages = session["pages"]
    index = session["index"]

    for m in pages[index]:
        await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=DB_CHANNEL_ID,
            message_id=m["message_id"]
        )

    await message.answer(
        f"📄 PAGE {index+1}/{len(pages)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅ Prev", callback_data="prev_page"),
                InlineKeyboardButton(text="Next ➡", callback_data="next_page")
            ]
        ])
    )

# =========================
# NEXT PAGE
# =========================

@dp.callback_query(F.data == "next_page")
async def next_page(call: CallbackQuery):

    uid = call.from_user.id
    session = user_page.get(uid)

    if not session:
        return await call.answer("No session", show_alert=True)

    if session["index"] + 1 >= len(session["pages"]):
        return await call.answer("Last page")

    session["index"] += 1

    await call.message.delete()
    await send_page(call.message, uid)

# =========================
# PREV PAGE
# =========================

@dp.callback_query(F.data == "prev_page")
async def prev_page(call: CallbackQuery):

    uid = call.from_user.id
    session = user_page.get(uid)

    if not session:
        return await call.answer("No session", show_alert=True)

    if session["index"] <= 0:
        return await call.answer("First page")

    session["index"] -= 1

    await call.message.delete()
    await send_page(call.message, uid)
# =========================
# RUN
# =========================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
