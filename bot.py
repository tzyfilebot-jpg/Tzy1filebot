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
page_message_id = {}

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
        "Kirim file sekarang.\n\n"
        "Gunakan tombol di bawah:",
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

    if not upload_session[uid]["active"]:
        return

    s = upload_session[uid]

    msg = await bot.copy_message(
        chat_id=DB_CHANNEL_ID,
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )

    t = message.content_type

    if t == "video":
        s["video"] += 1
    elif t == "photo":
        s["photo"] += 1
    elif t == "document":
        s["doc"] += 1

    add_media(
        s["code"],
        msg.message_id,
        t,
        None,
        0
    )
# =========================
# DONE UPLOAD DAN CANCEL
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
        s["video"] + s["photo"] + s["doc"],
        0
    )

    del upload_session[uid]

    await call.message.edit_text(
        "☠️ FILE LOCKED\n\n"
        f"🔑 {final_code}\n\n"
        "Jangan hilang."
    )


@dp.callback_query(F.data == "cancel_upload")
async def cancel_upload(call: CallbackQuery):

    uid = call.from_user.id

    upload_session.pop(uid, None)

    await call.message.edit_text("⚰️ Upload dibatalkan.")

# =========================

# GET FILE MENU (INI TARUH DI SINI)

# =========================

@dp.callback_query(F.data == "getfile")

async def getfile_menu(call: CallbackQuery):

    await call.message.edit_text(

        "📥 GET FILE MODE\n\n"

        "Kirim code seperti:\n"

        "tzy_xxx_5v_3p_1d"

    )

    await call.answer()
# =========================
# GET FILE SYSTEM
# =========================

@dp.message(F.text.regexp(r"^tzy_"))
async def get_file(message: Message):

    text = message.text.strip()
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

    uid = message.from_user.id

    user_page[uid] = {
        "pages": pages,
        "index": 0,
        "chat_id": message.chat.id
    }

    msg = await message.answer("📥 LOADING FILE...")

    page_message_id[uid] = msg.message_id

    await render_page(uid)
# =========================
# SEND PAGE
# =========================

async def render_page(uid):

    session = user_page.get(uid)
    if not session:
        return

    pages = session["pages"]
    index = session["index"]
    chat_id = session["chat_id"]

    if not pages:
        return

    text = f"📄 PAGE {index+1}/{len(pages)}\n\n"

    for m in pages[index]:
        text += f"📎 {m.get('media_type','FILE').upper()}\n"

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=page_message_id[uid],
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="⬅ Prev", callback_data="prev_page"),
                    InlineKeyboardButton(text="Next ➡", callback_data="next_page")
                ]
            ])
        )
    except:
        pass
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

    await render_page(uid)
    await call.answer()

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

    await render_page(uid)
    await call.answer()
# =========================
# RUN
# =========================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
