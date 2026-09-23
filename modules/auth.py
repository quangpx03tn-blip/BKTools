"""
modules/auth.py

Đăng nhập bằng Google (OAuth 2.0) và tách dữ liệu riêng cho từng tài khoản.

Mỗi Gmail đăng nhập sẽ có thư mục dữ liệu riêng:
    <DATA_DIR>/users/<hash-của-email>/projects/
    <DATA_DIR>/users/<hash-của-email>/profiles/

Nhờ đó hai người dùng khác nhau không bao giờ thấy project của nhau, kể cả
khi trùng tên project.

Cấu hình bằng biến môi trường (khai trong Railway → Variables):
    GOOGLE_CLIENT_ID      — lấy từ Google Cloud Console
    GOOGLE_CLIENT_SECRET  — lấy từ Google Cloud Console
    ALLOWED_EMAILS        — (tùy chọn) danh sách email được phép, cách nhau
                            bằng dấu phẩy. Bỏ trống = ai có Gmail cũng vào được.

Nếu KHÔNG khai GOOGLE_CLIENT_ID thì module tự tắt, hệ thống quay về cơ chế
username/password cũ — tiện chạy local.
"""

import hashlib
import json
import os
import re
import time

from flask import session


# ──────────────────────────────────────────────────────────────
#  CẤU HÌNH
# ──────────────────────────────────────────────────────────────

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

# Metadata chuẩn của Google, Authlib tự đọc endpoint từ đây
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


def _parse_allowed_emails():
    """
    Đọc danh sách email được phép từ biến môi trường.
    Bỏ trống -> trả về None, nghĩa là không giới hạn.
    """
    raw = os.environ.get("ALLOWED_EMAILS", "").strip()
    if not raw:
        return None
    emails = {e.strip().lower() for e in re.split(r"[,;\s]+", raw) if e.strip()}
    return emails or None


ALLOWED_EMAILS = _parse_allowed_emails()


def google_oauth_enabled() -> bool:
    """True khi đã khai đủ Client ID + Secret."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def is_email_allowed(email: str) -> bool:
    """Kiểm tra email có nằm trong danh sách cho phép không."""
    if ALLOWED_EMAILS is None:
        return True
    return (email or "").strip().lower() in ALLOWED_EMAILS


# ──────────────────────────────────────────────────────────────
#  KHÔNG GIAN DỮ LIỆU RIÊNG CHO TỪNG NGƯỜI DÙNG
# ──────────────────────────────────────────────────────────────

def user_key(email: str) -> str:
    """
    Sinh khóa thư mục từ email.

    Dùng hash thay vì email thô để:
      - tên thư mục luôn hợp lệ trên mọi hệ điều hành
      - không lộ email của người dùng qua đường dẫn file
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        return "anonymous"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def current_user_email() -> str:
    """Email của người đang đăng nhập, rỗng nếu chưa đăng nhập."""
    return (session.get("user_email") or "").strip().lower()


def current_user_key() -> str:
    """
    Khóa thư mục của người đang đăng nhập.

    Khi chạy local không bật OAuth, mọi thứ dồn vào "local" để giữ nguyên
    hành vi cũ — không phải đăng nhập vẫn dùng được.
    """
    email = current_user_email()
    if not email:
        return "local"
    return user_key(email)


def user_data_root(data_dir: str) -> str:
    """
    Thư mục gốc chứa dữ liệu của người dùng hiện tại.
    Tự tạo nếu chưa có.
    """
    root = os.path.join(data_dir, "users", current_user_key())
    os.makedirs(root, exist_ok=True)
    return root


def _migrate_legacy(data_dir: str, kind: str, dest: str):
    """
    Chuyển dữ liệu từ bố cục CŨ (dùng chung) sang thư mục riêng của người dùng.

    Trước khi có đăng nhập Google, mọi project/profile nằm chung ở
    <DATA_DIR>/projects và <DATA_DIR>/profiles. Sau khi tách theo tài khoản,
    số dữ liệu đó vẫn nằm nguyên chỗ cũ và không tool nào đọc tới — người
    dùng thấy như bị mất sạch.

    Hàm này COPY (không xóa bản gốc) sang thư mục của tài khoản đầu tiên
    mở tới. Giữ bản gốc để nếu di trú sai tài khoản vẫn còn đường lùi.
    Chỉ chạy một lần: đánh dấu bằng file .migrated trong thư mục đích.
    """
    legacy = os.path.join(data_dir, kind)
    if not os.path.isdir(legacy):
        return

    marker = os.path.join(dest, ".migrated")
    if os.path.exists(marker):
        return

    import shutil
    moved = 0
    try:
        for name in os.listdir(legacy):
            if not name.endswith(".json"):
                continue
            src = os.path.join(legacy, name)
            dst = os.path.join(dest, name)
            # Không ghi đè thứ người dùng đã tạo sau này
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                moved += 1
        with open(marker, "w", encoding="utf-8") as f:
            f.write(str(moved))
        if moved:
            print(f"[i] Đã chuyển {moved} file {kind} từ bố cục cũ sang {dest}")
    except OSError as e:
        # Di trú hỏng không được phép chặn người dùng dùng tool
        print(f"[!] Không chuyển được dữ liệu cũ ({kind}): {e}")


def user_projects_root(data_dir: str) -> str:
    """<DATA_DIR>/users/<key>/projects — tự tạo nếu chưa có."""
    path = os.path.join(user_data_root(data_dir), "projects")
    os.makedirs(path, exist_ok=True)
    _migrate_legacy(data_dir, "projects", path)
    return path


def user_profiles_root(data_dir: str) -> str:
    """<DATA_DIR>/users/<key>/profiles — tự tạo nếu chưa có."""
    path = os.path.join(user_data_root(data_dir), "profiles")
    os.makedirs(path, exist_ok=True)
    _migrate_legacy(data_dir, "profiles", path)
    return path


# ──────────────────────────────────────────────────────────────
#  SỔ NGƯỜI DÙNG (chỉ để thống kê / xem ai đã đăng nhập)
# ──────────────────────────────────────────────────────────────

def _registry_path(data_dir: str) -> str:
    return os.path.join(data_dir, "users", "_registry.json")


def record_login(data_dir: str, email: str, name: str = "", picture: str = ""):
    """
    Ghi nhận một lần đăng nhập vào sổ.

    Sổ này chỉ để bạn biết có những ai đang dùng tool; hệ thống không đọc nó
    để phân quyền, nên hỏng file cũng không ảnh hưởng đăng nhập.
    """
    try:
        os.makedirs(os.path.join(data_dir, "users"), exist_ok=True)
        path = _registry_path(data_dir)

        registry = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    registry = json.load(f) or {}
            except (json.JSONDecodeError, OSError):
                registry = {}

        key = user_key(email)
        entry = registry.get(key) or {}
        entry.update({
            "email": email,
            "name": name or entry.get("name", ""),
            "picture": picture or entry.get("picture", ""),
            "last_login": int(time.time()),
            "login_count": int(entry.get("login_count", 0)) + 1,
        })
        entry.setdefault("first_login", entry["last_login"])
        registry[key] = entry

        with open(path, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
    except Exception:
        # Ghi sổ thất bại không được phép chặn đăng nhập
        pass


def list_users(data_dir: str) -> list:
    """Danh sách người dùng đã từng đăng nhập, mới nhất trước."""
    path = _registry_path(data_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            registry = json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        return []
    users = list(registry.values())
    users.sort(key=lambda u: u.get("last_login", 0), reverse=True)
    return users
