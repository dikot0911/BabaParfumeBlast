import os
import asyncio
import random
from dotenv import load_dotenv
from telethon import TelegramClient

# Load variabel dari .env
load_dotenv()

api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
session_name = os.getenv('SESSION_NAME')
message_text = os.getenv('MESSAGE_TEXT').replace('\\n', '\n')
interval = int(os.getenv('INTERVAL', 14400))

# --- MAPPING GRUP & TOPIK ---
# Format: {ID_GRUP: [ID_TOPIK_1, ID_TOPIK_2]}
TARGET_MAP = {
    -1001111111111: [12, 45],  # Contoh: Grup A (Topik 12 & 45)
    -1002222222222: [99],      # Contoh: Grup B (Topik 99)
    -1003333333333: [7, 10, 5] # Contoh: Grup C (Topik 7, 10, 5)
    # Tambahkan sampai 16 grup lu di sini
}

client = TelegramClient(session_name, api_id, api_hash)

async def auto_share():
    print("Userbot started...")
    while True:
        print("\n--- Memulai siklus pengiriman ---")
        
        # Ambil semua grup dari mapping
        for group_id, topic_ids in TARGET_MAP.items():
            for t_id in topic_ids:
                try:
                    # Kirim pesan ke grup & topik spesifik
                    await client.send_message(
                        group_id, 
                        message_text, 
                        reply_to=t_id
                    )
                    print(f"✅ Terkirim: Grup {group_id} | Topik {t_id}")
                    
                    # Jeda random 30-60 detik biar gak kena ban
                    delay = random.randint(30, 60)
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    print(f"❌ Gagal di {group_id} Topik {t_id}: {e}")

        print(f"\n--- Siklus selesai. Tidur selama {interval/3600} jam... ---")
        await asyncio.sleep(interval)

async def main():
    # Pastikan login sukses
    await client.start()
    print("Client terhubung!")
    await auto_share()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
