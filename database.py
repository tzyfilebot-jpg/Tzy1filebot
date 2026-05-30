from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

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
        print(f"add_user error: {e}")


def get_user(user_id):
    try:
        result = supabase.table("users").select("*").eq(
            "user_id",
            user_id
        ).execute()

        return result.data[0] if result.data else None

    except Exception as e:
        print(f"get_user error: {e}")
        return None


def get_all_users():
    try:
        result = supabase.table("users").select("*").execute()
        return result.data

    except Exception as e:
        print(f"get_all_users error: {e}")
        return []


def total_users():
    try:
        result = supabase.table("users").select("*").execute()
        return len(result.data)

    except Exception:
        return 0


# =========================
# ADMINS
# =========================

def add_admin(user_id):
    try:
        return supabase.table("admins").upsert({
            "user_id": user_id
        }).execute()

    except Exception as e:
        print(f"add_admin error: {e}")


def remove_admin(user_id):
    try:
        return supabase.table("admins").delete().eq(
            "user_id",
            user_id
        ).execute()

    except Exception as e:
        print(f"remove_admin error: {e}")


def is_admin(user_id):
    try:
        result = supabase.table("admins").select("*").eq(
            "user_id",
            user_id
        ).execute()

        return bool(result.data)

    except Exception:
        return False


def get_admins():
    try:
        result = supabase.table("admins").select("*").execute()
        return result.data

    except Exception:
        return []


# =========================
# UPLOADS
# =========================

def create_upload(
    code,
    owner_id,
    total_files,
    total_size
):
    try:
        return supabase.table("uploads").insert({
            "code": code,
            "owner_id": owner_id,
            "total_files": total_files,
            "total_size": total_size
        }).execute()

    except Exception as e:
        print(f"create_upload error: {e}")


def get_upload(code):
    try:
        result = supabase.table("uploads").select("*").eq(
            "code",
            code
        ).execute()

        return result.data[0] if result.data else None

    except Exception as e:
        print(f"get_upload error: {e}")
        return None


def delete_upload(code):
    try:
        return supabase.table("uploads").delete().eq(
            "code",
            code
        ).execute()

    except Exception as e:
        print(f"delete_upload error: {e}")


def total_codes():
    try:
        result = supabase.table("uploads").select("*").execute()
        return len(result.data)

    except Exception:
        return 0


# =========================
# MEDIA
# =========================

def add_media(
    code,
    message_id,
    file_name,
    file_size
):
    try:
        return supabase.table("media").insert({
            "code": code,
            "message_id": message_id,
            "file_name": file_name,
            "file_size": file_size
        }).execute()

    except Exception as e:
        print(f"add_media error: {e}")


def get_media(code):
    try:
        result = supabase.table("media").select("*").eq(
            "code",
            code
        ).order("id").execute()

        return result.data

    except Exception as e:
        print(f"get_media error: {e}")
        return []


def delete_media(code):
    try:
        return supabase.table("media").delete().eq(
            "code",
            code
        ).execute()

    except Exception as e:
        print(f"delete_media error: {e}")


def total_media():
    try:
        result = supabase.table("media").select("*").execute()
        return len(result.data)

    except Exception:
        return 0


def total_storage():
    try:
        result = supabase.table("media").select(
            "file_size"
        ).execute()

        return sum(
            row["file_size"]
            for row in result.data
        )

    except Exception:
        return 0


# =========================
# STATISTICS
# =========================

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

def get_media_page(
    code,
    page=1,
    per_page=10
):
    media = get_media(code)

    start = (page - 1) * per_page
    end = start + per_page

    return media[start:end]


def get_total_pages(
    code,
    per_page=10
):
    media = get_media(code)

    if not media:
        return 1

    return (len(media) + per_page - 1) // per_page
