# Hướng dẫn đưa BK Tools lên web (GitHub + Railway)

Sau khi làm xong các bước dưới đây:
- Bạn mở link web bất kỳ đâu → nhập mật khẩu là vào được.
- Sửa code trên máy → `git push` → web tự cập nhật trong 1–2 phút.

---

## Thông tin đăng nhập web (đã cấu hình)

| Mục | Giá trị |
|-----|---------|
| Username | `HH_BKtools` |
| Password | `Rio@BK2026` |

Có thể đổi sau trong Railway → Variables (không cần sửa code).

---

## Bước 1 — Tạo tài khoản GitHub (miễn phí)

1. Vào https://github.com/signup
2. Đăng ký bằng email, xác nhận email.
3. Cài **GitHub Desktop** (dễ hơn dùng lệnh): https://desktop.github.com/
4. Mở GitHub Desktop → File → Options → Accounts → Sign in.

---

## Bước 2 — Đưa code lên GitHub lần đầu

1. Mở **GitHub Desktop**.
2. File → **Add local repository** → chọn thư mục:
   `E:\Bản đã ok\BK Tools - New`
   - Nếu báo “not a Git repository” → chọn **create a repository** ngay tại thư mục đó.
3. Ở ô Summary gõ: `first deploy`
4. Bấm **Commit to main**.
5. Bấm **Publish repository**:
   - Bỏ tick “Keep this code private” nếu muốn public (khuyến nghị **để private** vì tool riêng).
   - Bấm Publish.

Lưu ý: file `.env` **không** được đẩy lên GitHub (đã có trong `.gitignore`). API key và mật khẩu chỉ khai báo trên Railway.

---

## Bước 3 — Tạo tài khoản Railway

1. Vào https://railway.app
2. Sign up bằng **GitHub** (nút “Login with GitHub”) → cho phép Railway đọc repo.
3. Vào Dashboard → **New Project** → **Deploy from GitHub repo**.
4. Chọn repo vừa publish (`BK Tools - New` hoặc tên bạn đặt).
5. Railway sẽ tự build. Lần đầu có thể **fail** vì chưa có biến môi trường — bình thường, làm Bước 4.

---

## Bước 4 — Khai báo biến môi trường trên Railway

Vào project → service vừa tạo → tab **Variables** → thêm từng dòng:

```
APP_USERNAME=HH_BKtools
APP_PASSWORD=Rio@BK2026
SECRET_KEY=bat-ky-chuoi-dai-ngau-nhien-vi-du-9f3a2c1b8e7d6a5f
GEMINI_API_KEY=sk-... (dán đúng key bạn đang dùng trong file .env local)
FLASK_DEBUG=0
DATA_DIR=/data
```

Sau khi Save, Railway sẽ redeploy tự động.

---

## Bước 5 — Gắn Volume (để project/profile không mất khi update)

1. Trong service → **Settings** (hoặc tab Volumes) → **Add Volume**.
2. Mount path: `/data`
3. Save → đợi redeploy xong.

Nhờ `DATA_DIR=/data`, thư mục `projects/` và `profiles/` nằm trên Volume bền vững.

---

## Bước 6 — Lấy link web công khai

1. Settings → **Networking** → **Generate Domain**.
2. Railway cấp 1 URL dạng: `https://xxxx.up.railway.app`
3. Mở URL → thấy trang đăng nhập → nhập `HH_BKtools` / `Rio@BK2026`.

---

## Cách UPDATE sau này (mỗi lần sửa tool trên máy)

1. Sửa code trong `E:\Bản đã ok\BK Tools - New` (hoặc chạy local `python app.py` để test).
2. Mở **GitHub Desktop**:
   - Xem phần thay đổi bên trái.
   - Summary: ghi ngắn gọn, ví dụ `fix thumbnail tool`.
   - **Commit to main** → **Push origin**.
3. Railway tự nhận push và deploy lại (1–2 phút).
4. Refresh trang web → tính năng mới đã có. Dữ liệu project cũ vẫn còn (nhờ Volume).

Hoặc dùng file `update.bat` trong thư mục dự án (xem bên dưới).

---

## Chạy local (máy bạn)

1. Copy `.env.example` → `.env` nếu chưa có, điền đủ key + username/password.
2. Cài thư viện:
   ```
   pip install -r requirements.txt
   ```
3. Chạy:
   ```
   python app.py
   ```
4. Mở http://127.0.0.1:5000

Nếu `.env` có `APP_USERNAME` / `APP_PASSWORD` thì local cũng hỏi đăng nhập (giống web).

---

## Đổi mật khẩu / API key sau này

Chỉ cần vào Railway → Variables → sửa `APP_PASSWORD` hoặc `GEMINI_API_KEY` → Save. Không cần sửa code, không cần push Git.

---

## Xử lý lỗi thường gặp

| Hiện tượng | Cách xử lý |
|------------|------------|
| Build fail thiếu package | Kiểm tra `requirements.txt`, push lại |
| Mở web báo Application Error | Xem tab **Deployments** → View Logs |
| Đăng nhập không vào được | Kiểm tra Variables `APP_USERNAME` / `APP_PASSWORD` đúng chưa |
| Mất project sau redeploy | Chưa gắn Volume hoặc chưa đặt `DATA_DIR=/data` |
| Push bị từ chối | Trên GitHub Desktop: Repository → Pull trước, rồi Push lại |
