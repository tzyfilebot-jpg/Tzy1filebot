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

# =========================
# FORCE JOIN
# =========================
async def check_join(user_id: int):
    try:
        member = await bot.get_chat_member(UPDATE_CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
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


def vip_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔥 JOIN VIP NOW",
                url=f"https://t.me/{OWNER_ID}"
            )
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
            "⛓ AKSES TERKUNCI\nJoin channel dulu!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 JOIN CHANNEL", url=f"https://t.me/{UPDATE_CHANNEL.replace('@','')}")]
            ])
        )

    await message.answer(
        "🔥 FILE SYSTEM READY",
        reply_markup=main_menu()
    )


# =========================
# CALLBACK ROUTER
# =========================
@dp.callback_query()
async def cb(call: CallbackQuery):

    uid = call.from_user.id
    data = call.data

    if data == "help":
        return await call.message.answer(
            "📌 CARA PAKAI:\n\n"
            "📤 Upload → kirim file\n"
            "✔ DONE → simpan\n"
            "📥 Get → kirim code\n\n"
            "⚠ Code = tzy_xxx"
        )

    if data == "vip":
        return await call.message.answer(
            "💎 VIP PREMIUM\n\n"
            "💰 Rp150.000 / $10 / RM45\n\n"
            "🔥 Benefit:\n"
            "- Unlimited upload\n"
            "- Fast access\n"
            "- Priority support",
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

        return await call.message.answer(
            "📤 UPLOAD MODE ACTIVE\n\nKirim file sekarang",
            reply_markup=upload_menu()
        )

    if data == "getfile":
        return await call.message.answer("📥 SEND CODE (tzy_xxx)")

    if data == "done":
        if uid in upload_session:

            s = upload_session[uid]
            s["active"] = False

            code = s["code"]

            create_upload(code, uid, s["video"] + s["photo"] + s["doc"], 0)

            del upload_session[uid]

            return await call.message.answer(f"✅ SAVED\nKEY: {code}")

    if data == "cancel":
        upload_session.pop(uid, None)
        return await call.message.answer("❌ CANCELLED")

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
        users = get_all_users()

        for u in users:
            try:
                await bot.send_message(u["user_id"], text)
            except:
                pass

        broadcast_mode.remove(uid)
        return await message.answer("📢 SENT TO ALL USERS")

    # ================= GET FILE =================
    match = re.search(r"(tzy_[a-z0-9_]+)", text.lower())
    if match:

        code = match.group(1)

        now = time.time()
        if code in cooldown and now - cooldown[code] < 5:
            return await message.answer("⏳ COOLDOWN 5s")

        cooldown[code] = now

        media = get_media(code)

        if not media:
            return await message.answer("❌ CODE NOT FOUND")

        pages = [media[i:i+5] for i in range(0, len(media), 5)]

        user_page[uid] = {
            "pages": pages,
            "index": 0,
            "chat_id": message.chat.id
        }

        await message.answer("📥 LOADING FILE...")
        return await render(uid)

    # ================= ADMIN =================
    if text == "/statistik":
        if uid != OWNER_ID and not is_admin(uid):
            return

        users = total_users()

        # simple "grafik"
        bar = "█" * min(users // 10, 20)

        return await message.answer(
            f"📊 DASHBOARD\n\n"
            f"👤 USERS: {users}\n"
            f"{bar}"
        )

    if text == "/broadcast":
        if uid != OWNER_ID and not is_admin(uid):
            return

        broadcast_mode.add(uid)
        return await message.answer("📢 SEND BROADCAST MESSAGE")

    # ================= DONE / CANCEL =================
    if text.upper() == "DONE":
        if uid in upload_session:

            s = upload_session[uid]
            s["active"] = False

            code = s["code"]

            create_upload(code, uid, s["video"] + s["photo"] + s["doc"], 0)

            del upload_session[uid]

            return await message.answer(f"✅ SAVED\n{code}")

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

    msg = await bot.copy_message(
        chat_id=DB_CHANNEL_ID,  # 🔥 AUTO BACKUP PERMANENT
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

    await message.answer("📤 UPLOADED SUCCESS")


# =========================
# RENDER FILE PAGE
# =========================
async def render(uid):

    s = user_page.get(uid)
    if not s:
        return

    pages = s["pages"]
    idx = max(0, min(s["index"], len(pages) - 1))

    text = f"📄 PAGE {idx+1}/{len(pages)}\n\n"

    for m in pages[idx]:
        text += f"📎 {m.get('media_type','FILE')}\n"

    await bot.send_message(s["chat_id"], text)


# =========================
# RUN BOT
# =========================
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
