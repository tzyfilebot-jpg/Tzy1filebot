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

from config import BOT_TOKEN, OWNER_ID, DB_CHANNEL_ID
from database import add_user, is_admin, create_upload, add_media, get_media, total_users

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# STATE
# =========================
upload_session = {}
user_page = {}
cooldown = {}
broadcast_mode = set()


# =========================
# UI (MINI APP STYLE)
# =========================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Up File", callback_data="upload"),
            InlineKeyboardButton(text="📥 Get File", callback_data="getfile")
        ],
        [
            InlineKeyboardButton(text="❓ Help", callback_data="help"),
            InlineKeyboardButton(text="💎 VIP", callback_data="vip")
        ]
    ])


# =========================
# START
# =========================
@dp.message(CommandStart())
async def start(message: Message):
    u = message.from_user
    add_user(u.id, u.username, u.first_name)

    await message.answer(
        "🔥 MINI FILE SYSTEM ONLINE\nPilih menu di bawah",
        reply_markup=main_menu()
    )


# =========================
# CALLBACK ROUTER
# =========================
@dp.callback_query()
async def router(call: CallbackQuery):

    uid = call.from_user.id
    data = call.data

    # HELP
    if data == "help":
        return await call.message.answer(
            "📌 UPLOAD → kirim file\n"
            "📌 GET → kirim code\n"
            "📌 VIP → fitur premium"
        )

    # VIP
    if data == "vip":
        return await call.message.answer("💎 VIP belum aktif")

    # UPLOAD
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
            "📤 UPLOAD MODE ACTIVE\nKirim file sekarang\nKetik DONE / CANCEL"
        )

    # GET FILE
    if data == "getfile":
        return await call.message.answer("📥 Kirim code: tzy_xxx")

    await call.answer()


# =========================
# TEXT HANDLER
# =========================
@dp.message(F.text)
async def text_handler(message: Message):

    uid = message.from_user.id
    text = message.text.strip()

    # ================= BROADCAST =================
    if uid in broadcast_mode:
        for u in range(total_users()):
            try:
                await bot.send_message(u, text)
            except:
                pass
        broadcast_mode.remove(uid)
        return await message.answer("📢 SENT")

    # ================= DONE =================
    if text.upper() == "DONE":
        if uid in upload_session:
            s = upload_session[uid]
            s["active"] = False

            code = s["code"]

            create_upload(code, uid, s["video"] + s["photo"] + s["doc"], 0)

            del upload_session[uid]

            return await message.answer(f"✅ SAVED\n{code}")

    # ================= CANCEL =================
    if text.upper() == "CANCEL":
        upload_session.pop(uid, None)
        return await message.answer("❌ CANCELLED")

    # ================= GET FILE =================
    match = re.search(r"(tzy_[a-z0-9_]+)", text.lower())
    if not match:
        return

    code = match.group(1)

    now = time.time()
    if code in cooldown and now - cooldown[code] < 5:
        return await message.answer("⏳ cooldown")

    cooldown[code] = now

    media = get_media(code)
    if not media:
        return await message.answer("❌ NOT FOUND")

    pages = [media[i:i+5] for i in range(0, len(media), 5)]

    user_page[uid] = {
        "pages": pages,
        "index": 0,
        "chat_id": message.chat.id
    }

    await render(uid)


# =========================
# MEDIA HANDLER (AUTO BACKUP DB CHANNEL)
# =========================
@dp.message(F.content_type.in_({"video", "photo", "document"}))
async def media_handler(message: Message):

    uid = message.from_user.id

    if uid not in upload_session:
        return

    s = upload_session[uid]
    if not s["active"]:
        return

    # 🔥 AUTO BACKUP TO DB CHANNEL (PERSISTENT)
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


# =========================
# RENDER PAGE
# =========================
async def render(uid):

    s = user_page.get(uid)
    if not s:
        return

    pages = s["pages"]
    idx = max(0, min(s["index"], len(pages)-1))

    text = f"📄 PAGE {idx+1}/{len(pages)}\n\n"

    for m in pages[idx]:
        text += f"📎 {m.get('media_type','FILE')}\n"

    await bot.send_message(
        s["chat_id"],
        text
    )


# =========================
# ADMIN COMMANDS ONLY
# =========================
@dp.message(F.text == "/statistik")
async def stats(message: Message):

    if message.from_user.id != OWNER_ID and not is_admin(message.from_user.id):
        return

    await message.answer(f"📊 USERS: {total_users()}")


@dp.message(F.text == "/broadcast")
async def broadcast(message: Message):

    if message.from_user.id != OWNER_ID and not is_admin(message.from_user.id):
        return

    broadcast_mode.add(message.from_user.id)
    await message.answer("📢 SEND MESSAGE")


# =========================
# RUN
# =========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
