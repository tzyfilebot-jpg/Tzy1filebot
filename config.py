from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

DB_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID"))

OWNER_ID = int(os.getenv("OWNER_ID"))

UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL")
NOTIF_CHANNEL = os.getenv("NOTIF_CHANNEL")
