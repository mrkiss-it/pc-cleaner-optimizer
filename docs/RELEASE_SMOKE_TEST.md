# Checklist smoke-test phát hành / Release smoke-test

Chạy trên **Windows 10/11** trước mỗi GitHub Release: **cài mới → cập nhật → gỡ cài**.

Run on Windows before every GitHub Release: **fresh install → update → uninstall**.

| Mục | Giá trị / Value |
|---|---|
| Sản phẩm / Product | **PC Auto Cleaner & Optimizer** (`APP_NAME` trong `app_meta.py`) |
| Phiên bản / Version | `APP_VERSION` trong `app_meta.py` phải khớp git tag GitHub Release mới nhất (không hard-code số phiên bản ở đây) |
| Bộ cài / Setup asset | `dist/PCAutoCleaner_Setup.exe` (đúng tên này trên Release) |
| Thư mục cài / Install dir | `%LOCALAPPDATA%\Programs\PCAutoCleaner` |

**Fail ngay nếu** wizard / lối tắt hiện **Pro**, **`_Optimizer`**, hoặc Qt mnemonic (chữ `O` gạch chân) thay vì **& Optimizer**.

---

## 1. Build

- [ ] `python build_exe.py`
- [ ] `python installer/build_installer.py`
- [ ] Có `dist/PCAutoCleaner/PCAutoCleaner.exe`, `dist/PCAutoCleaner/uninstall.exe`, `dist/PCAutoCleaner_Setup.exe`

---

## 2. Cài mới / Fresh install

Chạy `PCAutoCleaner_Setup.exe` trên máy **chưa cài** (hoặc đã gỡ sạch).

- [ ] Tiêu đề / trang thành công hiện `v` + `APP_VERSION` khớp tag
- [ ] Tên sản phẩm đúng **PC Auto Cleaner & Optimizer** — không **Pro**, không **`_Optimizer`**
- [ ] Cài xong có `PCAutoCleaner.exe` **và** `uninstall.exe` trong thư mục cài
- [ ] Windows **Settings → Apps** hiện đúng tên + version
- [ ] Registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PCAutoCleaner`: `UninstallString` trỏ `uninstall.exe` (không phải `PCAutoCleaner.exe`)
- [ ] Lối tắt Desktop / Start Menu đúng tên (checkbox Setup mặc định bật)

---

## 3. Khởi chạy / First launch

- [ ] App mở được; **EULA hiện một lần**; đồng ý rồi **không hỏi lại** (lần sau chỉ xem lại trong Settings)
- [ ] Header / Settings hiện đúng `v{APP_VERSION}`
- [ ] **Cài đặt (Settings)** có đủ:
  - **Cập nhật** — Kiểm Tra Cập Nhật / Cập nhật
  - **Gỡ cài đặt** — nút trong Settings (không nhầm **Gỡ Phần Mềm** trên dashboard)
  - **Ổn định Wi-Fi**

---

## 4. Phát hành + cập nhật / Publish + Update

- [ ] GitHub Release: tag = `APP_VERSION`; asset đúng tên **`PCAutoCleaner_Setup.exe`**
- [ ] Máy đang chạy bản **cũ hơn** → Settings → **Kiểm Tra Cập Nhật** → thấy bản mới
- [ ] Bấm **Cập nhật**: tải Setup, **mở installer**, app **tự thoát** (để ghi đè file đang chạy)
- [ ] Setup nâng cấp xong; mở lại app đúng version mới

---

## 5. Gỡ cài / Uninstall

Cài lại giữa hai lần. Kiểm **cả hai lối**.

- [ ] **Trong app:** Settings → **Gỡ cài đặt** → xác nhận → `uninstall.exe` chạy, app thoát
- [ ] **Windows Apps:** Settings → Apps → **PC Auto Cleaner & Optimizer** → Uninstall
- [ ] Sau gỡ: hết thư mục cài + `uninstall.exe`; hết khóa Uninstall ở Registry; hết lối tắt Desktop / Start Menu (kể cả lối tắt gỡ cài)
- [ ] `%APPDATA%\PCAutoCleaner` **còn** nếu không chọn xóa cấu hình

---

## 6. Tùy chọn / Optional (không chặn phát hành)

- [ ] Có Gemini API key (Copilot) → chat chạy, không crash
- [ ] Wi-Fi yếu → thẻ/tip **Ổn định Wi-Fi** hiện; toast **không spam** (cooldown ~30 phút)

---

## Pass

Mục **1–5** đều tick. Mục 6 bỏ qua nếu không có key / Wi-Fi ổn.
