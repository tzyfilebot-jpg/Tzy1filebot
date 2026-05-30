import asyncio
import time
import secrets
import re

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart

from config import BOT_TOKEN, OWNER_ID, UPDATE_CHANNEL, DB_CHANNEL_ID
from database import (
    add_user,
    is_admin,
    create_upload,
    add_media,
    get_media,
    total_users,
    total_codes,
    total_media,
    get_all_users
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# STATE
# =========================
upload_session = {}
user_page = {}
broadcast_mode = set()


# =========================
# FORCE JOIN
# =========================
async def check_join(user_id: int):
    try:
        m = await bot.get_chat_member(UPDATE_CHANNEL, user_id)
        return m.status in ["member", "administrator", "creator"]
    except:
        return False


# =========================
# UI MENU USER
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


# =========================
# UPLOAD CONTROL MENU
# =========================
def upload_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ DONE", callback_data="done_upload"),
            InlineKeyboardButton(text="❌ CANCEL", callback_data="cancel_upload")
        ]
    ])


# =========================
# VIP BUTTON
# =========================
def vip_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔥 JOIN VIP NOW",
                url=f"https://t.me/{OWNER_ID}"
            )
        ],
        [
            InlineKeyboardButton(text="⬅ Back", callback_data="back")
        ]
    ])


# =========================
# START
# =========================
@dp.message(CommandStart())
async def start(message: Message):
    u = message.from_user
    add_user(u.id, u.username, u.first_name)

    if not await check_join(u.id):
        return await message.answer(
            "⛓ AKSES TERKUNCI\n\nJoin channel dulu untuk lanjut.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 JOIN CHANNEL", url=f"https://t.me/{UPDATE_CHANNEL.replace('@','')}")]
            ])
        )

    await message.answer(
        "🔥 FILE SYSTEM READY\nPilih menu di bawah",
        reply_markup=user_menu()
    )


# =========================
# CALLBACK ROUTER (CLEAN)
# =========================
@dp.callback_query()
async def cb(call: CallbackQuery):
    uid = call.from_user.id
    data = call.data

    # HELP
    if data == "help":
        return await call.message.answer(
            "💀 HOW TO USE BOT 💀\n\n"
            "📤 UPLOAD:\n- klik Up File\n- kirim media\n- DONE untuk simpan\n\n"
            "📥 GET FILE:\n- kirim code (tzy_xxx)\n\n"
            "⚠ Savage system: simple, fast, brutal"
        )

    # ACCOUNT
    if data == "account":
        u = call.from_user
        return await call.message.answer(
            f"👤 ACCOUNT\n\nNAME: {u.first_name}\nUSER: @{u.username or '-'}\nID: {u.id}"
        )

    # VIP
    if data == "vip":
        return await call.message.answer(
            "💎 VIP ACCESS\n\n💰 Rp 150.000 / $10 / RM45\n\n"
            "🔥 Benefits:\n- Unlimited upload\n- Fast access\n- Priority support",
            reply_markup=vip_menu()
        )

    # BACK
    if data == "back":
        return await call.message.answer("⬅ Back to menu", reply_markup=user_menu())

    # UPLOAD START
    if data == "upload":
        code = "tzy_" + secrets.token_hex(3)

        upload_session[uid] = {
            "code": code,
            "video": 0,
            "photo": 0,
            "doc": 0,
            "active": True
        }

        return await call.message.answer(
            "📤 UPLOAD MODE ACTIVE\n\nKirim media sekarang",
            reply_markup=upload_menu()
        )

    # GET FILE
    if data == "getfile":
        return await call.message.answer("📥 SEND CODE (tzy_xxx)")

    # DONE
    if data == "done_upload":
        if uid in upload_session:
            s = upload_session[uid]
            s["active"] = False

            code = s["code"]

            create_upload(
                code,
                uid,
                s["video"] + s["photo"] + s["doc"],
                0
            )

            del upload_session[uid]

            return await call.message.answer(
                f"✅ SAVED SUCCESS\n\nCODE:\n{code}\n\n🔗 READY TO USE"
            )

    # CANCEL
    if data == "cancel_upload":
        upload_session.pop(uid, None)
        return await call.message.answer("❌ UPLOAD CANCELLED")

    await call.answer()


# =========================
# TEXT HANDLER
# =========================
@dp.message(F.text)
async def text_handler(message: Message):

    uid = message.from_user.id
    text = message.text.strip()

    # BROADCAST
    if uid in broadcast_mode:
        users = get_all_users()
        for u in users:
            try:
                await bot.send_message(u["user_id"], text)
            except:
                pass

        broadcast_mode.remove(uid)
        return await message.answer("📢 SENT")

    # GET FILE BY CODE
    match = re.search(r"(tzy_[a-z0-9_]+)", text.lower())
    if match:
        code = match.group(1)

        media = get_media(code)

        if not media:
            return await message.answer("❌ FILE NOT FOUND")

        pages = [media[i:i+5] for i in range(0, len(media), 5)]

        user_page[uid] = {
            "pages": pages,
            "index": 0,
            "chat_id": message.chat.id
        }

        return await message.answer("📥 LOADING FILE...\nREADY")


    # ADMIN
    if text == "/statistik":
        if uid != OWNER_ID and not is_admin(uid):
            return

        return await message.answer(
            f"📊 DASHBOARD\n\n"
            f"👤 USERS: {total_users()}\n"
            f"📦 CODES: {total_codes()}\n"
            f"📎 MEDIA: {total_media()}"
        )

    if text == "/broadcast":
        if uid != OWNER_ID and not is_admin(uid):
            return

        broadcast_mode.add(uid)
        return await message.answer("📢 SEND BROADCAST MESSAGE")


# =========================
# MEDIA HANDLER (UPLOAD)
# =========================
@dp.message(F.content_type.in_({"video", "photo", "document"}))
async def media_handler(message: Message):

    uid = message.from_user.id

    if uid not in upload_session:
        return

    s = upload_session[uid]
    if not s["active"]:
        return

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

    add_media(s["code"], msg.message_id, t, 0)

    await message.answer("📤 SAVED ✔")


# =========================
# RUN BOT
# =========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
