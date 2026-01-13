import os
import asyncio
import random
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- AMBIL DARI ENV ---
API_ID_ENV = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
STRING_SESSION = os.getenv('STRING_SESSION')

# Validasi awal biar gak crash di Render
if not API_ID_ENV or not API_HASH or not STRING_SESSION:
    print("❌ ERROR: API_ID, API_HASH, atau STRING_SESSION belum diisi di Environment Variables!")
    sys.exit(1)

API_ID = int(API_ID_ENV)
API_HASH = API_HASH
# ID Grup Sumber & Pesan
SOURCE_CHAT_ID = int(os.getenv('SOURCE_CHAT_ID', '0'))
SOURCE_MSG_ID = int(os.getenv('SOURCE_MSG_ID', '0'))
INTERVAL = int(os.getenv('INTERVAL', 14400))

# --- MAPPING TARGET (LU EDIT DI SINI) ---
TARGET_MAP = {
    -1001111111111: [12, 45],  # Contoh: ID Grup & List ID Topik
    -1002222222222: [99],
    # Tambahkan semua 16 grup lu di sini
}

# Inisialisasi Client dengan StringSession
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

async def auto_forward():
    print("🚀 Userbot Baba Parfume Berjalan...")
    
    while True:
        print("\n--- Memulai Siklus Blast Baru ---")
        try:
            # Ambil pesan asli
            msg = await client.get_messages(SOURCE_CHAT_ID, ids=SOURCE_MSG_ID)
            
            if msg:
                groups = list(TARGET_MAP.items())
                random.shuffle(groups)
                
                for group_id, topic_ids in groups:
                    for t_id in topic_ids:
                        try:
                            await client.forward_messages(
                                entity=group_id,
                                messages=msg,
                                reply_to=t_id
                            )
                            print(f"✅ Berhasil ke: {group_id} | Topik: {t_id}")
                            await asyncio.sleep(random.randint(45, 90)) # Jeda lebih aman
                        except Exception as e:
                            print(f"❌ Gagal di grup {group_id} topik {t_id}: {e}")
            else:
                print("⚠️ Pesan sumber tidak ditemukan! Cek SOURCE_MSG_ID.")
        
        except Exception as e:
            print(f"⚠️ Error sistem: {e}")

        print(f"--- Selesai. Tidur {INTERVAL/3600} jam ---")
        await asyncio.sleep(INTERVAL)

async def main():
    try:
        # Gunakan connect() bukan start() biar gak nanya HP
        await client.connect()
        if not await client.is_user_authorized():
            print("❌ ERROR: String Session lu GAK VALID atau udah EXPIRED. Generate ulang bre!")
            return
        
        print("✅ Akun BERHASIL Terhubung!")
        await auto_forward()
    except Exception as e:
        print(f"❌ Gagal Login: {e}")

if __name__ == '__main__':
    asyncio.run(main())
