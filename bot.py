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

# BOT_TOKEN
# DATABASE_URL
# CHANNEL_DB
# FORCE_CHANNEL
# OWNER_ID

# =========================
# DATABASE
# =========================

# create_pool()
# create_tables()
# save_user()
# save_code()

# =========================
# KEYBOARDS
# =========================

# user keyboard
# admin keyboard

# =========================
# SESSION CACHE
# =========================

# upload_sessions
# user_states
# broadcast_states

# =========================
# FORCE SUB
# =========================

# check_force_sub()

# =========================
# START
# =========================

# /start

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
