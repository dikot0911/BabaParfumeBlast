import os
import asyncio
import random
import sys
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from threading import Thread
from supabase import create_client, Client

load_dotenv()

# --- KONFIGURASI SUPABASE ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ ERROR: SUPABASE_URL atau SUPABASE_KEY belum diisi!")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- KONFIGURASI TELEGRAM ---
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH')
STRING_SESSION = os.getenv('STRING_SESSION')
SOURCE_CHAT_ID = int(os.getenv('SOURCE_CHAT_ID', '0'))
SOURCE_MSG_ID = int(os.getenv('SOURCE_MSG_ID', '0'))

# Pesan Auto Reply
AUTO_REPLY_MSG = (
    "Selamat datang di Baba Parfume! ✨\n\n"
    "Lagi cari aroma apa nih kak? Untuk cewe apa cowo? "
    "Kalo belum punya aroma personal, biar mimin bantu rekomendasiin ya ^^"
)
# Jeda Auto Reply (dalam jam)
AUTO_REPLY_DELAY_HOURS = 6 

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# Penyimpanan memori sementara untuk mencatat waktu reply terakhir ke user
# Format: {user_id: datetime_object}
last_replies = {}

# --- WEB SERVER & PANEL ---
app = Flask(__name__)
app.secret_key = 'baba_parfume_super_secret'

@app.route('/')
def dashboard():
    logs = supabase.table('blast_logs').select("*").order('created_at', desc=True).limit(20).execute()
    schedules = supabase.table('blast_schedules').select("*").order('run_hour').execute()
    targets = supabase.table('blast_targets').select("*").order('created_at').execute()
    
    return render_template('index.html', 
                         logs=logs.data, 
                         schedules=schedules.data,
                         targets=targets.data)

@app.route('/add_schedule', methods=['POST'])
def add_schedule():
    hour = request.form.get('hour')
    minute = request.form.get('minute')
    if hour:
        supabase.table('blast_schedules').insert({"run_hour": int(hour), "run_minute": int(minute)}).execute()
    return redirect(url_for('dashboard'))

@app.route('/delete_schedule/<int:id>')
def delete_schedule(id):
    supabase.table('blast_schedules').delete().eq('id', id).execute()
    return redirect(url_for('dashboard'))

@app.route('/add_target', methods=['POST'])
def add_target():
    name = request.form.get('group_name')
    gid = request.form.get('group_id')
    topics = request.form.get('topic_ids')
    if name and gid:
        supabase.table('blast_targets').insert({
            "group_name": name,
            "group_id": int(gid),
            "topic_ids": topics
        }).execute()
    return redirect(url_for('dashboard'))

@app.route('/delete_target/<int:id>')
def delete_target(id):
    supabase.table('blast_targets').delete().eq('id', id).execute()
    return redirect(url_for('dashboard'))

def run_web():
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- FITUR 1: AUTO REPLY (EVENT HANDLER) ---
@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    """
    Fungsi ini otomatis jalan setiap ada pesan baru masuk.
    """
    try:
        # 1. Pastikan ini pesan personal (DM), bukan grup
        if not event.is_private:
            return
        
        sender = await event.get_sender()
        sender_id = sender.id
        
        # Hindari membalas diri sendiri atau bot lain (opsional)
        if sender.bot:
            return

        now = datetime.now()

        # 2. Cek Cooldown (Jeda Waktu)
        if sender_id in last_replies:
            last_time = last_replies[sender_id]
            # Hitung selisih waktu
            time_diff = now - last_time
            
            # Jika belum lewat 6 jam (atau sesuai setting), abaikan (jangan reply)
            if time_diff < timedelta(hours=AUTO_REPLY_DELAY_HOURS):
                return
        
        # 3. Kirim Pesan Auto Reply
        # Kita pakai random delay dikit biar makin mirip manusia (2-5 detik ngetik)
        await asyncio.sleep(random.randint(2, 5))
        await event.reply(AUTO_REPLY_MSG)
        
        # 4. Catat waktu pengiriman
        last_replies[sender_id] = now
        print(f"📩 Auto-Reply terkirim ke: {sender_id} ({sender.first_name})")

    except Exception as e:
        print(f"⚠️ Error Auto-Reply: {e}")

# --- FITUR 2: LOGGING KE DATABASE ---
def log_to_db(group_name, group_id, topic_id, status, error_msg=""):
    try:
        data = {
            "group_name": group_name,
            "group_id": group_id,
            "topic_id": topic_id,
            "status": status,
            "error_message": str(error_msg)
        }
        supabase.table('blast_logs').insert(data).execute()
    except Exception as e:
        print(f"⚠️ Gagal log DB: {e}")

# --- FITUR 3: AUTO BLAST (LOOPING) ---
async def auto_forward():
    print(f"🚀 Userbot Standby. Full Controlled by Panel & Auto-Reply Active.")
    last_run_time = None
    
    while True:
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        current_time_str = f"{current_hour}:{current_minute}"
        
        # Cek Jadwal Aktif dari Database
        try:
            sched_res = supabase.table('blast_schedules').select("*").eq('is_active', True).execute()
            schedules = sched_res.data
        except:
            schedules = []

        is_time = False
        for s in schedules:
            if s['run_hour'] == current_hour and s['run_minute'] == current_minute:
                is_time = True
                break
        
        if is_time and current_time_str != last_run_time:
            print(f"\n--- ⏰ MULAI BLASTING: {current_time_str} ---")
            
            try:
                target_res = supabase.table('blast_targets').select("*").eq('is_active', True).execute()
                targets = target_res.data
            except Exception as e:
                print(f"Gagal ambil target: {e}")
                targets = []

            if targets:
                try:
                    msg = await client.get_messages(SOURCE_CHAT_ID, ids=SOURCE_MSG_ID)
                    if msg:
                        random.shuffle(targets)
                        
                        for target in targets:
                            raw_topics = target.get('topic_ids', '')
                            if raw_topics:
                                t_ids = [int(x.strip()) for x in raw_topics.split(',') if x.strip().isdigit()]
                            else:
                                t_ids = [None] # Kirim ke grup biasa (bukan topik)

                            for t_id in t_ids:
                                try:
                                    await client.forward_messages(target['group_id'], msg, reply_to=t_id)
                                    print(f"✅ Sukses: {target['group_name']} | Topik {t_id}")
                                    log_to_db(target['group_name'], target['group_id'], t_id, "SUCCESS")
                                    # Jeda agak lama biar aman
                                    await asyncio.sleep(random.randint(45, 90))
                                except Exception as e:
                                    print(f"❌ Gagal: {target['group_name']} ({e})")
                                    log_to_db(target['group_name'], target['group_id'], t_id, "FAILED", str(e))
                        
                        last_run_time = current_time_str
                        print("--- ✅ Siklus Selesai ---")
                    else:
                        print("⚠️ Pesan Sumber Tidak Ditemukan!")
                except Exception as e:
                    print(f"⚠️ Error Eksekusi Blast: {e}")

        # Cek jadwal setiap 30 detik
        await asyncio.sleep(30)

async def start_bot():
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("❌ SESSION EXPIRED/INVALID")
            return
        print("✅ BOT CONNECTED - Siap Blast & Auto Reply")
        
        # Kita jalankan auto_forward di background, sementara client tetap listen event message
        # Namun karena auto_forward adalah infinite loop, kita panggil langsung aja.
        # Telethon events berjalan secara async di background loop yang sama.
        await auto_forward()
        
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == '__main__':
    Thread(target=run_web).start()
    asyncio.run(start_bot())
