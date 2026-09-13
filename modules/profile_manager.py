import json
import os

PROFILE_FILE = "profiles_data.json"

def load_profiles():
    """Đọc danh sách toàn bộ profile từ file JSON lưu trữ."""
    if not os.path.exists(PROFILE_FILE):
        return []
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_profiles(profiles):
    """Lưu danh sách profile vào file JSON."""
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=4)

def create_profile(data):
    """Tạo mới một profile kênh."""
    profiles = load_profiles()
    
    # Gán ID tự tăng hoặc dùng timestamp
    new_id = len(profiles) + 61 # Bắt đầu từ số 061 như trong giao diện của bạn
    data["id"] = f"{new_id:03d}"
    
    profiles.append(data)
    save_profiles(profiles)
    return data["id"]

def get_profile_by_id(profile_id):
    """Lấy thông tin chi tiết của một profile theo ID."""
    profiles = load_profiles()
    for p in profiles:
        if p.get("id") == profile_id:
            return p
    return None 

def delete_profile(profile_id):
    """Xóa một profile theo ID khỏi danh sách và lưu lại file JSON."""
    profiles = load_profiles()
    initial_length = len(profiles)
    
    # Lọc giữ lại những profile không trùng với ID cần xóa
    profiles = [p for p in profiles if str(p.get("id")) != str(profile_id)]
    
    # Nếu danh sách sau khi lọc ngắn hơn nghĩa là đã xóa thành công
    if len(profiles) < initial_length:
        save_profiles(profiles)
        return True
    return False