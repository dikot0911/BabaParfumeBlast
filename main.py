import os
import asyncio
import random
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# Load environment variables
load_dotenv()

# --- DUMMY WEB SERVER UNTUK RENDER ---
# Ini WAJIB ada supaya Render gak nganggep deploy gagal (Port Timeout)
app = Flask('')

@app.route('/')
def home():
    return "Baba Parfume Userbot is Running!"

def run_web():
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- AMBIL DARI ENV ---
API_ID_ENV = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
STRING_SESSION = os.getenv('STRING_SESSION')

# Validasi awal
if not API_ID_ENV or not API_HASH or not STRING_SESSION:
    print("❌ ERROR: API_ID, API_HASH, atau STRING_SESSION kosong!")
    sys.exit(1)

API_ID = int(API_ID_ENV)
API_HASH = API_HASH
SOURCE_CHAT_ID = int(os.getenv('SOURCE_CHAT_ID', '0'))
SOURCE_MSG_ID = int(os.getenv('SOURCE_MSG_ID', '0'))
INTERVAL = int(os.getenv('INTERVAL', 14400))

# --- MAPPING TARGET (PASTIKAN ID SUDAH BENER BRE) ---
TARGET_MAP = {
    -1001111111111: [12, 45],  # Ganti pake ID grup & topik asli lu
    -1002222222222: [99],
}

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

async def auto_forward():
    print("🚀 Userbot Baba Parfume Berjalan...")
    while True:
        print("\n--- Memulai Siklus Blast Baru ---")
        try:
            msg = await client.get_messages(SOURCE_CHAT_ID, ids=SOURCE_MSG_ID)
            if msg:
                groups = list(TARGET_MAP.items())
                random.shuffle(groups)
                for group_id, topic_ids in groups:
                    for t_id in topic_ids:
                        try:
                            await client.forward_messages(group_id, msg, reply_to=t_id)
                            print(f"✅ Berhasil ke: {group_id} | Topik: {t_id}")
                            await asyncio.sleep(random.randint(60, 120)) # Jeda lebih manusiawi
                        except Exception as e:
                            print(f"❌ Gagal di grup {group_id}: {e}")
            else:
                print("⚠️ Pesan sumber tidak ditemukan! Cek SOURCE_MSG_ID.")
        except Exception as e:
            print(f"⚠️ Error sistem: {e}")

        print(f"--- Selesai. Tidur {INTERVAL/3600} jam ---")
        await asyncio.sleep(INTERVAL)

async def start_bot():
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("❌ ERROR: STRING_SESSION LU SALAH ATAU EXPIRED!")
            return
        print("✅ AKUN BERHASIL TERHUBUNG!")
        await auto_forward()
    except Exception as e:
        print(f"❌ Gagal Koneksi: {e}")

if __name__ == '__main__':
    # Jalankan Web Server di thread berbeda
    Thread(target=run_web).start()
    # Jalankan Bot
    asyncio.run(start_bot())
