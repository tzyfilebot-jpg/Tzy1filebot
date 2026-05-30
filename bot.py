import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

from config import BOT_TOKEN, OWNER_ID, UPDATE_CHANNEL, NOTIF_CHANNEL
from database import add_user, is_admin


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


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
            InlineKeyboardButton(text="💎 Join VIP", callback_data="vip")
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
            InlineKeyboardButton(text="📊 Statistik", callback_data="stats"),
            InlineKeyboardButton(text="📢 Broadcast", callback_data="broadcast")
        ]
    ])


# =========================
# FORCE JOIN
# =========================

async def check_join(bot, user_id: int):
    try:
        ch1 = await bot.get_chat_member(UPDATE_CHANNEL, user_id)
        ch2 = await bot.get_chat_member(NOTIF_CHANNEL, user_id)

        valid = {"member", "administrator", "creator"}

        return ch1.status in valid and ch2.status in valid
    except:
        return False


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):
    user = message.from_user

    add_user(user.id, user.username, user.first_name)

    joined = await check_join(bot, user.id)

    if not joined:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Join Update", url=f"https://t.me/{UPDATE_CHANNEL.replace('@','')}")
            ],
            [
                InlineKeyboardButton(text="🔔 Join Notif", url=f"https://t.me/{NOTIF_CHANNEL.replace('@','')}")
            ],
            [
                InlineKeyboardButton(text="✅ Sudah Join", callback_data="check_join")
            ]
        ])

        return await message.answer(
            "⚠️ Berhenti.\n\n"
            "Masuk dulu ke channel.\n"
            "Baru bot bisa dipakai.",
            reply_markup=kb
        )

    text = (
        "☠️ Selamat datang.\n\n"
        "Aku menyimpan file.\n"
        "Sisanya bukan urusanku.\n\n"
        "🔑 Simpan code.\n"
        "Aku tidak memberi kesempatan kedua."
    )

    if user.id == OWNER_ID or is_admin(user.id):
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=user_menu())


# =========================
# CALLBACK SIMPLE (DUMMY DULU)
# =========================

@dp.callback_query(F.data == "check_join")
async def recheck(call: CallbackQuery):
    ok = await check_join(bot, call.from_user.id)

    if ok:
        await call.message.edit_text(
            "☠️ Akses diberikan.\n\nSilakan lanjut."
        )
    else:
        await call.answer("Belum join.", show_alert=True)


@dp.callback_query(F.data == "help")
async def help_cmd(call: CallbackQuery):
    await call.message.answer(
        "📖 Cara pakai:\n\n"
        "Upload → Done → Simpan Code\n"
        "Get File → Tempel Code\n\n"
        "Sesederhana itu."
    )


@dp.callback_query(F.data == "account")
async def account(call: CallbackQuery):
    user = call.from_user
    await call.message.answer(
        f"👤 Account\n\n"
        f"ID: {user.id}\n"
        f"Username: @{user.username}"
    )


@dp.callback_query(F.data == "vip")
async def vip(call: CallbackQuery):
    await call.message.answer(
        "💎 VIP\n\n"
        "Untuk yang tidak suka menunggu."
    )


# =========================
# RUN
# =========================

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
