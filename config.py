import os
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
