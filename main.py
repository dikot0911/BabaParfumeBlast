import os
import asyncio
import random
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
STRING_SESSION = os.getenv('STRING_SESSION')
# ID Grup Sumber (Baba Parfume) - Pastikan akun lu ada di sana
SOURCE_CHAT_ID = int(os.getenv('SOURCE_CHAT_ID'))
# ID Pesan Template yang mau di-forward
SOURCE_MSG_ID = int(os.getenv('SOURCE_MSG_ID'))
# Jeda antar blast (default 4 jam)
INTERVAL = int(os.getenv('INTERVAL', 14400))

# --- MAPPING TARGET (Grup ID -> List Topik ID) ---
# Silakan sesuaikan ID-ID ini dengan target lu
TARGET_MAP = {
    -1001111111111: [12, 45],  # Contoh Grup 1: Topik 12 & 45
    -1002222222222: [99],      # Contoh Grup 2: Topik 99
    # ... Tambahkan sampai 16 grup di sini
}

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

async def auto_forward():
    print("🚀 Userbot Baba Parfume sedang berjalan...")
    
    while True:
        print("\n--- Memulai Siklus Blast ---")
        try:
            # Ambil pesan dari grup sumber
            # entity bisa pake ID grup langsung
            msg = await client.get_messages(SOURCE_CHAT_ID, ids=SOURCE_MSG_ID)
            
            if msg:
                for group_id, topic_ids in TARGET_MAP.items():
                    for t_id in topic_ids:
                        try:
                            # Forward pesan ke grup dan topik tertentu
                            await client.forward_messages(
                                entity=group_id,
                                messages=msg,
                                reply_to=t_id # ID Topik di Telegram Forum
                            )
                            print(f"✅ Berhasil forward ke Grup {group_id} | Topik {t_id}")
                            
                            # Jeda random 30-60 detik biar gak dianggap robot brutal oleh Telegram
                            await asyncio.sleep(random.randint(30, 60))
                        except Exception as e:
                            print(f"❌ Gagal di {group_id} Topik {t_id}: {e}")
            else:
                print("⚠️ Pesan sumber tidak ditemukan. Cek SOURCE_MSG_ID!")
        
        except Exception as e:
            print(f"⚠️ Error Utama: {e}")

        print(f"--- Siklus Selesai. Tidur {INTERVAL/3600} Jam... ---")
        await asyncio.sleep(INTERVAL)

async def main():
    await client.start()
    print("✅ Akun berhasil terhubung!")
    await auto_forward()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
