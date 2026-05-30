from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# =========================
# USERS
# =========================

def add_user(user_id, username=None, first_name=None):
    try:
        return supabase.table("users").upsert({
            "user_id": user_id,
            "username": username,
            "first_name": first_name
        }).execute()
    except Exception as e:
        print("add_user error:", e)


def is_admin(user_id):
    try:
        res = supabase.table("admins").select("user_id").eq("user_id", user_id).execute()
        return bool(res.data)
    except Exception as e:
        print("is_admin error:", e)
        return False


# 🔥 FIX IMPORTANT (INI YANG KAMU TANYA)
def get_all_users():
    try:
        res = supabase.table("users").select("user_id").execute()
        return res.data or []
    except Exception as e:
        print("get_all_users error:", e)
        return []


# =========================
# UPLOADS
# =========================

def create_upload(code, owner_id, total_files, total_size):
    try:
        return supabase.table("uploads").insert({
            "code": code,
            "owner_id": owner_id,
            "total_files": total_files,
            "total_size": total_size
        }).execute()
    except Exception as e:
        print("create_upload error:", e)


def get_upload(code):
    try:
        res = supabase.table("uploads").select("*").eq("code", code).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print("get_upload error:", e)
        return None


# =========================
# MEDIA
# =========================

def add_media(code, message_id, media_type, file_name=None, file_size=0):
    try:
        return supabase.table("media").insert({
            "code": code,
            "message_id": message_id,
            "media_type": media_type,
            "file_name": file_name,
            "file_size": file_size
        }).execute()
    except Exception as e:
        print("add_media error:", e)


def get_media(code):
    try:
        res = (
            supabase.table("media")
            .select("*")
            .eq("code", code)
            .order("id")
            .execute()
        )
        return res.data or []
    except Exception as e:
        print("get_media error:", e)
        return []


# =========================
# STATISTICS (OPTIMIZED)
# =========================

def total_users():
    try:
        res = supabase.table("users").select("user_id", count="exact").execute()
        return res.count or 0
    except:
        return 0


def total_codes():
    try:
        res = supabase.table("uploads").select("code", count="exact").execute()
        return res.count or 0
    except:
        return 0


def total_media():
    try:
        res = supabase.table("media").select("id", count="exact").execute()
        return res.count or 0
    except:
        return 0


def total_storage():
    try:
        res = supabase.table("media").select("file_size").execute()
        return sum(x.get("file_size") or 0 for x in res.data or [])
    except:
        return 0


def get_statistics():
    return {
        "users": total_users(),
        "codes": total_codes(),
        "media": total_media(),
        "storage": total_storage()
    }


# =========================
# PAGINATION
# =========================

def get_media_page(code, page=1, per_page=5):
    try:
        media = get_media(code)

        if not media:
            return []

        start = (page - 1) * per_page
        end = start + per_page

        return media[start:end]
    except:
        return []


def get_total_pages(code, per_page=5):
    try:
        media = get_media(code)

        if not media:
            return 1

        return (len(media) + per_page - 1) // per_page
    except:
        return 1
