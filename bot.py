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
    get_all_users,
    total_users
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= STATE =================
upload_session = {}
cooldown = {}
broadcast_mode = set()


# ================= FORCE JOIN =================
async def check_join(user_id: int):
    try:
        res = await bot.get_chat_member(UPDATE_CHANNEL, user_id)
        return res.status in ["member", "administrator", "creator"]
    except:
        return False


# ================= UI =================
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 UPLOAD", callback_data="upload")],
        [InlineKeyboardButton(text="📥 GET FILE", callback_data="getfile")],
        [
            InlineKeyboardButton(text="❓ HELP", callback_data="help"),
            InlineKeyboardButton(text="💎 VIP", callback_data="vip")
        ]
    ])


def upload_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ DONE", callback_data="done"),
            InlineKeyboardButton(text="❌ CANCEL", callback_data="cancel")
        ]
    ])


def vip_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 JOIN VIP", url=f"https://t.me/{OWNER_ID}")]
    ])


# ================= START =================
@dp.message(CommandStart())
async def start(message: Message):

    u = message.from_user
    add_user(u.id, u.username, u.first_name)

    if not await check_join(u.id):
        return await message.answer(
            "⛓ AKSES TERKUNCI\nJoin channel dulu!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 JOIN CHANNEL", url=f"https://t.me/{UPDATE_CHANNEL.replace('@','')}")]
            ])
        )

    await message.answer("🔥 FILE SYSTEM READY", reply_markup=menu())


# ================= CALLBACK =================
@dp.callback_query()
async def cb(call: CallbackQuery):

    uid = call.from_user.id
    data = call.data

    if data == "help":
        return await call.message.answer(
            "📌 CARA PAKAI:\n"
            "- UPLOAD → kirim file\n"
            "- DONE → simpan\n"
            "- GET → kirim code"
        )

    if data == "vip":
        return await call.message.answer(
            "💎 VIP PREMIUM\n"
            "Rp 150.000 / $10 / RM45\n\n"
            "✔ Unlimited upload\n✔ Fast access",
            reply_markup=vip_btn()
        )

    if data == "upload":
        code = "tzy_" + secrets.token_hex(3)

        upload_session[uid] = {
            "code": code,
            "video": 0,
            "photo": 0,
            "doc": 0,
            "active": True
        }

        return await call.message.answer("📤 UPLOAD MODE ON", reply_markup=upload_menu())

    if data == "getfile":
        return await call.message.answer("📥 SEND CODE (tzy_xxx)")

    if data == "done":
        if uid in upload_session:
            s = upload_session[uid]
            create_upload(s["code"], uid, s["video"] + s["photo"] + s["doc"], 0)
            del upload_session[uid]
            return await call.message.answer(f"✅ SAVED\nCODE: {s['code']}")

    if data == "cancel":
        upload_session.pop(uid, None)
        return await call.message.answer("❌ CANCELLED")

    await call.answer()


# ================= TEXT =================
@dp.message(F.text)
async def text(message: Message):

    uid = message.from_user.id
    txt = message.text.strip()

    # ===== BROADCAST =====
    if uid in broadcast_mode:
        for u in get_all_users():
            try:
                await bot.send_message(u["user_id"], txt)
            except:
                pass
        broadcast_mode.remove(uid)
        return await message.answer("📢 SENT")

    # ===== ADMIN =====
    if txt == "/statistik":
        if uid != OWNER_ID and not is_admin(uid):
            return
        return await message.answer(f"👤 USERS: {total_users()}")

    if txt == "/broadcast":
        if uid != OWNER_ID and not is_admin(uid):
            return
        broadcast_mode.add(uid)
        return await message.answer("📢 SEND MESSAGE")

    # ===== GET FILE =====
    match = re.search(r"(tzy_[a-z0-9_]+)", txt.lower())
    if match:
        code = match.group(1)

        if code in cooldown and time.time() - cooldown[code] < 3:
            return await message.answer("⏳ COOLDOWN")

        cooldown[code] = time.time()

        media = get_media(code)

        if not media:
            return await message.answer("❌ NOT FOUND")

        for m in media:
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=DB_CHANNEL_ID,
                message_id=m["message_id"]
            )

        return

    # ===== DONE / CANCEL =====
    if txt.upper() == "DONE":
        if uid in upload_session:
            s = upload_session[uid]
            create_upload(s["code"], uid, s["video"] + s["photo"] + s["doc"], 0)
            del upload_session[uid]
            return await message.answer(f"✅ SAVED\n{s['code']}")

    if txt.upper() == "CANCEL":
        upload_session.pop(uid, None)
        return await message.answer("❌ CANCELLED")


# ================= MEDIA =================
@dp.message(F.content_type.in_({"video", "photo", "document"}))
async def media(message: Message):

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

    if message.content_type == "video":
        s["video"] += 1
    elif message.content_type == "photo":
        s["photo"] += 1
    else:
        s["doc"] += 1

    add_media(s["code"], msg.message_id, message.content_type, 0, 0)

    await message.answer("📤 UPLOADED")


# ================= RUN =================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
