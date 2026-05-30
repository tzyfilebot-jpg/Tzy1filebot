# =========================
# IMPORT
# =========================

import os
import re
import json
import asyncio
import secrets
import string
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)

from aiogram.filters import Command, CommandStart
# =========================
# CONFIG
# =========================

import os
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

CHANNEL_DB = os.getenv("CHANNEL_DB")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

ADMINS = set(
    int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip().isdigit()
)

FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL")
NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL")

VIP_LINK = os.getenv("VIP_LINK")

# =========================
# GLOBAL DB POOL
# =========================

db_pool: asyncpg.Pool = None


# =========================
# DATABASE CONNECT
# =========================

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        command_timeout=60
    )

    async with db_pool.acquire() as conn:
        # USERS
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_at TIMESTAMP DEFAULT NOW()
        )
        """)

        # CODES
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            owner_id BIGINT,
            total_media INT,
            total_size BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)

        # MEDIA
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS medias (
            id SERIAL PRIMARY KEY,
            code TEXT,
            file_id TEXT,
            file_type TEXT,
            message_id BIGINT,
            file_size BIGINT
        )
        """)

        # ADMINS
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY
        )
        """)


# =========================
# DB HELPERS
# =========================

async def add_user(user_id: int, username: str, full_name: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO users (user_id, username, full_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO NOTHING
        """, user_id, username, full_name)


async def save_code(code: str, owner_id: int, total_media: int, total_size: int):
    async with db_pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO codes (code, owner_id, total_media, total_size)
        VALUES ($1, $2, $3, $4)
        """, code, owner_id, total_media, total_size)


async def save_media(code: str, file_id: str, file_type: str, message_id: int, file_size: int):
    async with db_pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO medias (code, file_id, file_type, message_id, file_size)
        VALUES ($1, $2, $3, $4, $5)
        """, code, file_id, file_type, message_id, file_size)


async def get_code_data(code: str):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
        SELECT * FROM medias WHERE code=$1 ORDER BY id ASC
        """, code)


async def get_stats():
    async with db_pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        codes = await conn.fetchval("SELECT COUNT(*) FROM codes")
        media = await conn.fetchval("SELECT COUNT(*) FROM medias")
        return users, codes, media

# =========================
# KEYBOARDS
# =========================

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_keyboard(is_admin: bool = False):
    keyboard = [
        [
            KeyboardButton(text="📤 Up File"),
            KeyboardButton(text="📥 Get File")
        ],
        [
            KeyboardButton(text="👤 Account"),
            KeyboardButton(text="💎 VIP")
        ]
    ]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True
    )
# =========================
# SESSION CACHE
# =========================

upload_sessions = {}   # menyimpan media sementara saat UP FILE
user_states = {}       # status user: idle / upload / getfile / broadcast
broadcast_states = {}  # status admin saat broadcast aktif

# =========================
# FORCE SUB
# =========================

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

async def check_force_sub(bot: Bot, user_id: int, channel: str) -> bool:
    try:
        if channel.startswith("@"):
            channel = channel[1:]

        member = await bot.get_chat_member(
            chat_id=f"@{channel}",
            user_id=user_id
        )

        return member.status in ("member", "administrator", "creator")

    except TelegramBadRequest:
        return False
    except Exception:
        return False


# =========================
# START
# =========================

from aiogram import Router, F
from aiogram.types import Message

router = Router()

from config import FORCE_CHANNEL, ADMINS
from keyboards import get_keyboard  # kalau keyboard kamu di file terpisah

@router.message(F.text == "/start")
async def start_cmd(message: Message, bot: Bot):
    user_id = message.from_user.id

    is_joined = await check_force_sub(bot, user_id, FORCE_CHANNEL)

    if not is_joined:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        if FORCE_CHANNEL.startswith("@"):
            ch = FORCE_CHANNEL[1:]
        else:
            ch = FORCE_CHANNEL

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📢 Join Channel",
                        url=f"https://t.me/{ch}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Saya Sudah Join",
                        callback_data="check_sub"
                    )
                ]
            ]
        )

        await message.answer(
            "⚠ Kamu harus join channel dulu sebelum pakai bot",
            reply_markup=kb
        )
        return

    is_admin = user_id in ADMINS

    await message.answer(
        "🔥 Menu Bot Aktif",
        reply_markup=get_keyboard(is_admin)
    )
# =========================
# UP FILE
# =========================

# upload mode

# =========================
# DONE
# =========================

# generate code

# =========================
# CANCEL
# =========================

# cancel upload

# =========================
# GET FILE
# =========================

# receive code

# =========================
# PAGINATION
# =========================

# prev next

# =========================
# HELP
# =========================

# help menu

# =========================
# ACCOUNT
# =========================

# account info

# =========================
# VIP
# =========================

# vip menu

# =========================
# ADMIN PANEL
# =========================

# admin commands

# =========================
# ADD ADMIN
# =========================

# /addadmin

# =========================
# STATISTIC
# =========================

# /stat

# =========================
# BROADCAST
# =========================

# /broadcast

# =========================
# STARTUP
# =========================

# asyncio.run(main())
