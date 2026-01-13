import os
import asyncio
import random
import sys
import json
from datetime import datetime, timedelta
from telethon import TelegramClient, events, types
from telethon.sessions import StringSession
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
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

# Auto Reply Settings
AUTO_REPLY_MSG = (
    "Selamat datang di Baba Parfume! ✨\n\n"
    "Lagi cari aroma apa nih kak? Untuk cewe apa cowo? "
    "Kalo belum punya aroma personal, biar mimin bantu rekomendasiin ya ^^"
)
AUTO_REPLY_DELAY_HOURS = 6 

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
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

# --- FITUR BARU: SCAN GRUP DARI TELEGRAM ---
async def fetch_telegram_dialogs():
    """Mengambil daftar grup dan topik langsung dari akun lu"""
    groups_data = []
    
    # Ambil semua dialog (limit 100 biar gak berat, bisa dinaikin)
    async for dialog in client.iter_dialogs(limit=200):
        if dialog.is_group:
            entity = dialog.entity
            g_data = {
                'id': entity.id,
                'name': entity.title,
                'is_forum': getattr(entity, 'forum', False),
                'topics': []
            }

            # Kalau grupnya Forum/Topic-based, scan topiknya
            if g_data['is_forum']:
                try:
                    # Ambil topik yang aktif/open
                    topics = await client.get_forum_topics(entity, limit=30)
                    for t in topics.topics:
                        g_data['topics'].append({
                            'id': t.id,
                            'title': t.title
                        })
                except Exception as e:
                    print(f"⚠️ Gagal fetch topik {entity.title}: {e}")
            
            groups_data.append(g_data)
            
    return groups_data

@app.route('/scan_groups_api')
def scan_groups_api():
    """API Bridge buat Flask manggil fungsi Async Telethon"""
    try:
        # Menjalankan fungsi async di dalam event loop bot yang sedang berjalan
        future = asyncio.run_coroutine_threadsafe(fetch_telegram_dialogs(), client.loop)
        result = future.result(timeout=60) # Tunggu max 60 detik
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/save_bulk_targets', methods=['POST'])
def save_bulk_targets():
    """Menyimpan hasil checklist dari panel"""
    try:
        # Data dikirim via JSON dari Frontend
        data = request.json
        selected_items = data.get('targets', [])

        # Hapus semua target lama (Reset) biar sinkron sama checklist baru
        # Kalau mau mode 'tambah' (bukan replace), baris ini dihapus/komen aja
        # supabase.table('blast_targets').delete().neq('id', 0).execute() 

        count = 0
        for item in selected_items:
            # item format: {'group_id': 123, 'group_name': 'abc', 'topic_ids': [1, 2]}
            
            # Format topic_ids jadi string "1, 2, 3"
            topics_str = ", ".join(map(str, item['topic_ids']))
            
            # Cek dulu apakah grup ini udah ada di DB biar gak duplikat
            existing = supabase.table('blast_targets').select('id').eq('group_id', item['group_id']).execute()
            
            if existing.data:
                # Update kalau udah ada
                supabase.table('blast_targets').update({
                    "topic_ids": topics_str,
                    "group_name": item['group_name']
                }).eq('group_id', item['group_id']).execute()
            else:
                # Insert baru
                supabase.table('blast_targets').insert({
                    "group_name": item['group_name'],
                    "group_id": int(item['group_id']),
                    "topic_ids": topics_str
                }).execute()
            count += 1
            
        return jsonify({"status": "success", "message": f"{count} Grup berhasil disimpan!"})
    except Exception as e:
        print(f"Error saving: {e}")
        return jsonify({"status": "error", "message": str(e)})

# --- ROUTES JADWAL & HAPUS TARGET (SAMA KEK KEMAREN) ---
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

@app.route('/delete_target/<int:id>')
def delete_target(id):
    supabase.table('blast_targets').delete().eq('id', id).execute()
    return redirect(url_for('dashboard'))

def run_web():
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- TELETHON EVENTS & LOGIC (SAMA KEK KEMAREN) ---
@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    if not event.is_private: return
    sender = await event.get_sender()
    if not sender or sender.bot: return
    
    sender_id = sender.id
    now = datetime.now()
    if sender_id in last_replies:
        if now - last_replies[sender_id] < timedelta(hours=AUTO_REPLY_DELAY_HOURS):
            return
            
    await asyncio.sleep(random.randint(2, 5))
    try:
        await event.reply(AUTO_REPLY_MSG)
        last_replies[sender_id] = now
        print(f"📩 Auto-Reply: {sender.first_name}")
    except: pass

def log_to_db(group_name, group_id, topic_id, status, error_msg=""):
    try:
        supabase.table('blast_logs').insert({
            "group_name": group_name,
            "group_id": group_id,
            "topic_id": topic_id,
            "status": status,
            "error_message": str(error_msg)
        }).execute()
    except Exception as e: print(f"DB Log Error: {e}")

async def auto_forward():
    print(f"🚀 Userbot Standby. Panel Ready.")
    last_run_time = None
    
    while True:
        now = datetime.now()
        current_time_str = f"{now.hour}:{now.minute}"
        
        try:
            sched_res = supabase.table('blast_schedules').select("*").eq('is_active', True).execute()
            schedules = sched_res.data
        except: schedules = []

        is_time = False
        for s in schedules:
            if s['run_hour'] == now.hour and s['run_minute'] == now.minute:
                is_time = True; break
        
        if is_time and current_time_str != last_run_time:
            print(f"\n--- ⏰ BLASTING START: {current_time_str} ---")
            try:
                targets = supabase.table('blast_targets').select("*").eq('is_active', True).execute().data
                if targets:
                    msg = await client.get_messages(SOURCE_CHAT_ID, ids=SOURCE_MSG_ID)
                    if msg:
                        random.shuffle(targets)
                        for target in targets:
                            raw_topics = target.get('topic_ids', '')
                            t_ids = [int(x.strip()) for x in raw_topics.split(',') if x.strip().isdigit()] if raw_topics else [None]
                            for t_id in t_ids:
                                try:
                                    await client.forward_messages(target['group_id'], msg, reply_to=t_id)
                                    log_to_db(target['group_name'], target['group_id'], t_id, "SUCCESS")
                                    await asyncio.sleep(random.randint(45, 90))
                                except Exception as e:
                                    log_to_db(target['group_name'], target['group_id'], t_id, "FAILED", str(e))
                        last_run_time = current_time_str
            except Exception as e: print(f"Blast Error: {e}")
        await asyncio.sleep(30)

async def start_bot():
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ SESSION INVALID"); return
    print("✅ BOT CONNECTED")
    await auto_forward()

if __name__ == '__main__':
    Thread(target=run_web).start()
    asyncio.run(start_bot())
