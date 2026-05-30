import asyncio
import time
import secrets
import re
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

from config import BOT_TOKEN, OWNER_ID, UPDATE_CHANNEL, DB_CHANNEL_ID
from database import (
    add_user,
    is_admin,
    create_upload,
    add_media,
    get_media,
    total_users,
    get_all_users
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# STATE
# =========================
upload_session = {}
user_page = {}
cooldown = {}
broadcast_mode = set()
user_cooldown = {}

# =========================
# SQLITE SAFE MODE (ANTI CORRUPT)
# =========================
def db_safe_exec(query, args=()):
    conn = sqlite3.connect("database.db", timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()
    cur.execute(query, args)
    conn.commit()
    conn.close()


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
# UI
# =========================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 UPLOAD FILE", callback_data="upload")],
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


# =========================
# START
# =========================
@dp.message(CommandStart())
async def start(message: Message):

    u = message.from_user
    add_user(u.id, u.username, u.first_name)

    if not await check_join(u.id):
        return await message.answer(
            "⛓ LOCKED\nJoin channel dulu!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("JOIN CHANNEL", url=f"https://t.me/{UPDATE_CHANNEL.replace('@','')}")]
            ])
        )

    await message.answer("🔥 SYSTEM ONLINE", reply_markup=main_menu())


# =========================
# CALLBACK
# =========================
@dp.callback_query()
async def cb(call: CallbackQuery):

    uid = call.from_user.id
    d = call.data

    if d == "help":
        return await call.message.answer(
            "📌 GUIDE\n\nUPLOAD → kirim file\nDONE → simpan\nGET → pakai code"
        )

    if d == "vip":
        return await call.message.answer("💎 VIP ACTIVE SOON")

    if d == "upload":
        code = "tzy_" + secrets.token_hex(3)

        upload_session[uid] = {
            "code": code,
            "video": 0,
            "photo": 0,
            "doc": 0,
            "active": True
        }

        return await call.message.answer("📤 UPLOAD MODE ACTIVE", reply_markup=upload_menu())

    if d == "getfile":
        return await call.message.answer("📥 SEND CODE tzy_xxx")

    if d == "done":
        if uid in upload_session:
            s = upload_session[uid]
            s["active"] = False

            code = s["code"]
            create_upload(code, uid, s["video"] + s["photo"] + s["doc"], 0)

            del upload_session[uid]

            return await call.message.answer(f"✅ SAVED {code}")

    if d == "cancel":
        upload_session.pop(uid, None)
        return await call.message.answer("❌ CANCELLED")

    await call.answer()


# =========================
# TEXT HANDLER (ANTI SPAM + QUEUE)
# =========================
@dp.message(F.text)
async def text_handler(message: Message):

    uid = message.from_user.id
    text = message.text.strip()

    # ================= COOLDOWN GLOBAL =================
    now = time.time()
    if uid in user_cooldown and now - user_cooldown[uid] < 1:
        return
    user_cooldown[uid] = now

    # ================= BROADCAST =================
    if uid in broadcast_mode:
        users = get_all_users()

        batch = []
        for u in users:
            batch.append(u["user_id"])

            if len(batch) >= 10:
                await send_batch(batch, text)
                batch = []
                await asyncio.sleep(1)

        if batch:
            await send_batch(batch, text)

        broadcast_mode.remove(uid)
        return await message.answer("📢 BROADCAST DONE")


    # ================= ADMIN DASHBOARD =================
    if text == "/statistik":
        if uid != OWNER_ID and not is_admin(uid):
            return

        users = total_users()

        bar = "█" * min(users // 10, 20)

        return await message.answer(
            f"📊 REALTIME DASHBOARD\n\n"
            f"👤 USERS: {users}\n"
            f"{bar}"
        )

    if text == "/broadcast":
        if uid != OWNER_ID and not is_admin(uid):
            return

        broadcast_mode.add(uid)
        return await message.answer("📢 SEND MESSAGE")


    # ================= GET FILE =================
    match = re.search(r"(tzy_[a-z0-9_]+)", text.lower())
    if match:

        code = match.group(1)

        if code in cooldown and now - cooldown[code] < 5:
            return await message.answer("⏳ COOLDOWN")

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

        return await render(uid)


    # ================= DONE =================
    if text.upper() == "DONE":
        if uid in upload_session:

            s = upload_session[uid]
            s["active"] = False

            code = s["code"]

            create_upload(code, uid, s["video"] + s["photo"] + s["doc"], 0)

            del upload_session[uid]

            return await message.answer(f"✅ SAVED {code}")


    if text.upper() == "CANCEL":
        upload_session.pop(uid, None)
        return await message.answer("❌ CANCELLED")


# =========================
# MEDIA HANDLER (AUTO BACKUP)
# =========================
@dp.message(F.content_type.in_({"video", "photo", "document"}))
async def media_handler(message: Message):

    uid = message.from_user.id

    if uid not in upload_session:
        return

    s = upload_session[uid]
    if not s["active"]:
        return

    await bot.copy_message(
        chat_id=DB_CHANNEL_ID,
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )

    add_media(s["code"], message.message_id, message.content_type, 0)

    await message.answer("📤 UPLOADED")


# =========================
# SAFE SEND BATCH (FAST BROADCAST)
# =========================
async def send_batch(users, text):
    for uid in users:
        try:
            await bot.send_message(uid, text)
        except:
            pass


# =========================
# RENDER
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

    await bot.send_message(s["chat_id"], text)


# =========================
# RUN
# =========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
