# 🤖 Baba Parfume – Telegram Automation Bot

**Baba Parfume Bot** adalah sistem otomatisasi Telegram berbasis **Userbot** yang dirancang khusus untuk mendukung operasional dan pemasaran bisnis parfum secara efisien, humanis, dan terukur.

Bot ini menggabungkan:
- **Telethon** (interaksi Telegram layaknya manusia),
- **Flask** (dashboard web),
- **Supabase (PostgreSQL)** sebagai database CRM real-time.

Cocok untuk brand yang ingin **scale up** tanpa kehilangan sentuhan personal.

---

## ✨ Fitur Utama

### 🚀 1. Auto Blast & Forwarding (Human-like)
Mengirim pesan promosi ke ratusan grup secara otomatis **tanpa terlihat seperti bot**.

**Fitur:**
- Support **Forum / Topic Group**
- Smart Entity Resolver (auto handle Channel ID & User ID)
- Random Delay (anti spam detection)
- Pause / Resume / Stop Blast via Dashboard
- Retry otomatis saat network error / invalid peer

---

### 💬 2. CRM & Database Pelanggan
Sistem CRM otomatis langsung dari Telegram.

**Fungsi:**
- Auto save user dari PM (ID, username, nama)
- Import ribuan chat lama ke database
- Broadcast massal dengan **personal greeting**


---

### 🤖 3. Auto Reply Cerdas
Balasan otomatis saat admin offline atau untuk sapaan awal.

**Support:**
- Markdown (bold, italic, clickable link)
- Typing simulation
- Anti-spam reply (interval control)

---

### 📅 4. Penjadwalan Otomatis (WIB)
- Timezone aware (UTC+7)
- Tambah / hapus jadwal blast via dashboard
- Tidak perlu edit code

---

### 🖥️ 5. Web Dashboard Panel
Panel kontrol berbasis web untuk monitoring & manajemen bot.

**Fitur Dashboard:**
- Realtime blast status & progress
- Log sukses / gagal
- Group scanner (ambil semua grup akun)
- Target group & topic management

---

## 🛠️ Teknologi yang Digunakan

| Teknologi | Fungsi |
|---------|-------|
| Python | Core logic |
| Telethon | Telegram Userbot (MTProto) |
| Flask | Web dashboard |
| Supabase (PostgreSQL) | Database & CRM |
| Asyncio | Non-blocking process |
| Tailwind CSS | UI dashboard |

---

## 📂 Struktur Database (Supabase)

Bot menggunakan **4 tabel utama**:

### 1️⃣ `tele_users`
Menyimpan data pelanggan (CRM)
- `user_id`
- `username`
- `first_name`
- `last_interaction`

### 2️⃣ `blast_targets`
Target grup promosi
- `group_id`
- `group_name`
- `topic_ids`
- `is_active`

### 3️⃣ `blast_schedules`
Jadwal blast otomatis
- `run_hour`
- `run_minute`
- `is_active`

### 4️⃣ `blast_logs`
Log pengiriman pesan
- status sukses / gagal
- timestamp

---

## 🚀 Instalasi & Penggunaan

### 🔧 Prasyarat
- Python **3.9+**
- Akun Telegram (disarankan akun kedua)
- Akun Supabase
- API ID & API Hash dari `my.telegram.org`

---

### 🔐 Konfigurasi Environment

# Telegram Auth
API_ID=123456
API_HASH=abcdef123456
STRING_SESSION=YOUR_TELETHON_SESSION

# Supabase
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_KEY=your_supabase_key

# Source Message
SOURCE_CHAT_ID=123456789
SOURCE_MSG_ID=100

# Web Port
PORT=8080

❤️ Penutup

Dibuat untuk membantu bisnis Baba Parfume berkembang lebih cepat, rapi, dan scalable tanpa kehilangan sentuhan manusia.

Automation should feel human, not robotic.

