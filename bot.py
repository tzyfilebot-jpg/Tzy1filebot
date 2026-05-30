import asyncio
import time
import secrets
import re
import hashlib

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

from config import BOT_TOKEN, OWNER_ID, DB_CHANNEL_ID
from database import add_user, is_admin, create_upload, add_media, get_media, get_all_users

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# STATE (RAM CACHE ONLY)
# =========================
upload_session = {}
user_page = {}
cooldown = {}
broadcast_mode = set()
dashboard_msg = {}

# =========================
# SECURE CODE SYSTEM (PERMANENT READY)
# =========================
def gen_code():
    raw = f"{time.time()}{secrets.token_hex(6)}"
    return "tzy_" + hashlib.md5(raw.encode()).hexdigest()[:10]


# =========================
# MINI APP UI (PAGE SYSTEM)
# =========================
def menu(page=1):

    if page == 1:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 UPLOAD FILE", callback_data="up")],
            [InlineKeyboardButton(text="📥 GET FILE", callback_data="get")],
            [InlineKeyboardButton(text="📊 DASHBOARD", callback_data="dash")],
            [InlineKeyboardButton(text="❓ HELP", callback_data="help")],
            [InlineKeyboardButton(text="💎 VIP", callback_data="vip")]
        ])

    if page == 2:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ BACK MENU", callback_data="home")]
        ])


# =========================
# START
# =========================
@dp.message(CommandStart())
async def start(message: Message):

    u = message.from_user
    add_user(u.id, u.username, u.first_name)

    await message.answer(
        "☠ MINI APP SYSTEM ONLINE\nFILE MANAGER ACTIVE",
        reply_markup=menu(1)
    )


# =========================
# CALLBACK ROUTER (MINI APP STYLE)
# =========================
@dp.callback_query()
async def cb(call: CallbackQuery):

    uid = call.from_user.id
    data = call.data

    # HOME
    if data == "home":
        await call.message.edit_text("☠ MAIN MENU", reply_markup=menu(1))

    # HELP
    elif data == "help":
        await call.message.answer(
            "📌 UPLOAD → kirim file\n"
            "📌 GET → pakai code\n"
            "📌 DONE / CANCEL → kontrol upload"
        )

    # VIP
    elif data == "vip":
        await call.message.answer("💎 VIP SYSTEM OFF")

    # UPLOAD START
    elif data == "up":
        code = gen_code()

        upload_session[uid] = {
            "code": code,
            "video": 0,
            "photo": 0,
            "doc": 0,
            "active": True
        }

        await call.message.answer(
            "📤 UPLOAD MODE ACTIVE\nKirim file sekarang\n\nDONE / CANCEL"
        )

    # GET FILE
    elif data == "get":
        await call.message.answer("📥 SEND CODE (tzy_...)")

    # DASHBOARD (ADMIN ONLY)
    elif data == "dash":

        if uid != OWNER_ID and not is_admin(uid):
            return await call.answer("NO ACCESS", show_alert=True)

        users = len(get_all_users())

        msg = await call.message.answer(
            f"📊 LIVE DASHBOARD\n\n"
            f"👤 USERS: {users}\n"
            f"📦 ACTIVE UPLOAD: {len(upload_session)}\n"
            f"📥 ACTIVE SESSIONS: {len(user_page)}"
        )

        dashboard_msg[uid] = msg.message_id

    await call.answer()


# =========================
# TEXT ROUTER (UPLOAD + GET + ADMIN CMD)
# =========================
@dp.message(F.text)
async def text_router(message: Message):

    uid = message.from_user.id
    text = message.text.strip()

    # =========================
    # BROADCAST MODE
    # =========================
    if uid in broadcast_mode:
        for u in get_all_users():
            try:
                await bot.send_message(u["user_id"], text)
            except:
                pass

        broadcast_mode.remove(uid)
        return await message.answer("📢 BROADCAST SENT")

    # =========================
    # ADMIN COMMANDS
    # =========================
    if text.startswith("/statistik"):
        if uid != OWNER_ID and not is_admin(uid):
            return await message.answer("NO ACCESS")

        return await message.answer(f"👤 USERS: {len(get_all_users())}")

    if text.startswith("/broadcast"):
        if uid != OWNER_ID and not is_admin(uid):
            return await message.answer("NO ACCESS")

        msg = text.replace("/broadcast", "").strip()

        if not msg:
            return await message.answer("FORMAT: /broadcast pesan")

        for u in get_all_users():
            try:
                await bot.send_message(u["user_id"], msg)
            except:
                pass

        return await message.answer("📢 DONE")

    # =========================
    # DONE UPLOAD
    # =========================
    if text.upper() == "DONE":
        if uid in upload_session:
            s = upload_session[uid]
            s["active"] = False

            code = s["code"]
            create_upload(code, uid, s["video"] + s["photo"] + s["doc"], 0)

            upload_session.pop(uid, None)

            return await message.answer(f"✅ SAVED\n🔑 {code}")

    # =========================
    # CANCEL UPLOAD
    # =========================
    if text.upper() == "CANCEL":
        upload_session.pop(uid, None)
        return await message.answer("❌ CANCELLED")

    # =========================
    # GET FILE SYSTEM
    # =========================
    match = re.search(r"(tzy_[a-z0-9_]+)", text.lower())
    if not match:
        return

    code = match.group(1)

    now = time.time()
    if code in cooldown and now - cooldown[code] < 5:
        return await message.answer("⏳ COOLDOWN")

    cooldown[code] = now

    media = get_media(code)
    if not media:
        return await message.answer("❌ INVALID CODE")

    pages = [media[i:i+5] for i in range(0, len(media), 5)]

    user_page[uid] = {
        "pages": pages,
        "index": 0,
        "chat_id": message.chat.id
    }

    msg = await message.answer("📥 LOADING FILE...")

    await render(uid, msg.message_id)


# =========================
# MEDIA HANDLER (UPLOAD SAVE)
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


# =========================
# RENDER PAGE (SAFE UI)
# =========================
async def render(uid, msg_id):

    s = user_page.get(uid)
    if not s:
        return

    pages = s["pages"]
    idx = max(0, min(s["index"], len(pages)-1))

    text = f"📄 FILE PAGE {idx+1}/{len(pages)}\n\n"

    for m in pages[idx]:
        text += f"📎 {m.get('media_type','FILE')}\n"

    try:
        await bot.edit_message_text(
            chat_id=s["chat_id"],
            message_id=msg_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="⬅", callback_data="prev"),
                    InlineKeyboardButton(text="➡", callback_data="next")
                ]
            ])
        )
    except:
        pass


# =========================
# PAGINATION
# =========================
@dp.callback_query(F.data == "next")
async def next_page(call: CallbackQuery):
    s = user_page.get(call.from_user.id)
    if s and s["index"] + 1 < len(s["pages"]):
        s["index"] += 1
        await render(call.from_user.id, page_msg.get(call.from_user.id, 0))
    await call.answer()


@dp.callback_query(F.data == "prev")
async def prev_page(call: CallbackQuery):
    s = user_page.get(call.from_user.id)
    if s and s["index"] > 0:
        s["index"] -= 1
        await render(call.from_user.id, page_msg.get(call.from_user.id, 0))
    await call.answer()


# =========================
# RUN BOT
# =========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
