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
DB_UPDATE_INTERVAL_HOURS = 1 # Update database 'last_interaction' max 1 jam sekali biar gak spam DB

# --- GLOBAL VARIABLES ---
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
last_replies = {} # Cache untuk Auto Reply
user_db_cache = {} # Cache untuk Database Saver (Biar hemat request)
BOT_LOOP = None 
BROADCAST_RUNNING = False # Flag status broadcast

# --- WEB SERVER & PANEL ---
app = Flask(__name__)
app.secret_key = 'baba_parfume_super_secret'

@app.route('/')
def dashboard():
    logs = supabase.table('blast_logs').select("*").order('created_at', desc=True).limit(10).execute()
    schedules = supabase.table('blast_schedules').select("*").order('run_hour').execute()
    targets = supabase.table('blast_targets').select("*").order('created_at').execute()
    
    # Hitung total user CRM
    try:
        user_count = supabase.table('tele_users').select("user_id", count='exact').execute().count
    except:
        user_count = 0
        
    return render_template('index.html', 
                         logs=logs.data, 
                         schedules=schedules.data,
                         targets=targets.data,
                         user_count=user_count,
                         broadcast_running=BROADCAST_RUNNING)

# --- FITUR 1: SCAN GRUP (UPDATED DEBUGGING) ---
async def fetch_telegram_dialogs():
    groups_data = []
    if not client.is_connected(): await client.connect()
    
    print("🔄 Memulai Scan Grup Telegram...")
    
    # Naikkan limit dialog biar grup yang tenggelam juga keambil
    async for dialog in client.iter_dialogs(limit=300):
        if dialog.is_group:
            entity = dialog.entity
            is_forum = getattr(entity, 'forum', False)
            
            g_data = {
                'id': entity.id, 
                'name': entity.title, 
                'is_forum': is_forum, 
                'topics': []
            }
            
            # Logika Scan Topik yang lebih detail
            if is_forum:
                print(f"🔍 Forum Ditemukan: {entity.title}")
                try:
                    # Naikkan limit topik jadi 50
                    topics = await client.get_forum_topics(entity, limit=50)
                    if topics and topics.topics:
                        for t in topics.topics:
                            g_data['topics'].append({'id': t.id, 'title': t.title})
                        print(f"   ✅ Sukses ambil {len(g_data['topics'])} topik.")
                    else:
                        print("   ⚠️ Tidak ada topik terbuka/ditemukan.")
                except Exception as e:
                    print(f"   ❌ Gagal fetch topik {entity.title}: {e}")
            
            groups_data.append(g_data)
            
    print(f"✅ Scan Selesai. {len(groups_data)} grup ditemukan.")
    return groups_data

@app.route('/scan_groups_api')
def scan_groups_api():
    global BOT_LOOP
    try:
        if BOT_LOOP is None: return jsonify({"status": "error", "message": "Bot startup..."})
        future = asyncio.run_coroutine_threadsafe(fetch_telegram_dialogs(), BOT_LOOP)
        return jsonify({"status": "success", "data": future.result(timeout=60)})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

# --- FITUR 2: SAVE TARGETS ---
@app.route('/save_bulk_targets', methods=['POST'])
def save_bulk_targets():
    try:
        data = request.json
        selected = data.get('targets', [])
        for item in selected:
            topics_str = ", ".join(map(str, item['topic_ids']))
            exist = supabase.table('blast_targets').select('id').eq('group_id', item['group_id']).execute()
            if exist.data:
                supabase.table('blast_targets').update({"topic_ids": topics_str, "group_name": item['group_name']}).eq('group_id', item['group_id']).execute()
            else:
                supabase.table('blast_targets').insert({"group_name": item['group_name'], "group_id": int(item['group_id']), "topic_ids": topics_str}).execute()
        return jsonify({"status": "success", "message": "Disimpan!"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

# --- FITUR 3: CRM BROADCAST / FOLLOW UP ---
async def run_broadcast_task(message_text):
    global BROADCAST_RUNNING
    BROADCAST_RUNNING = True
    print("📢 MULAI BROADCAST FOLLOW UP...")
    
    try:
        # 1. Ambil semua user dari Database
        # Note: Kalau user jutaan, perlu pagination. Tapi untuk ribuan, fetch all masih oke.
        response = supabase.table('tele_users').select("user_id, first_name").execute()
        users = response.data
        
        total_users = len(users)
        sent_count = 0
        batch_size = 50
        
        print(f"🎯 Target Broadcast: {total_users} users")

        for i in range(0, total_users, batch_size):
            batch = users[i:i+batch_size]
            print(f"🚀 Mengirim Batch {i+1} sampai {i+len(batch)}...")
            
            for user in batch:
                try:
                    # Ganti {name} dengan nama user kalau ada di template
                    final_msg = message_text.replace("{name}", user.get('first_name') or "Kak")
                    
                    await client.send_message(int(user['user_id']), final_msg)
                    sent_count += 1
                    
                    # Human Delay (2-3 detik)
                    await asyncio.sleep(random.uniform(2.0, 3.5))
                    
                except Exception as e:
                    print(f"❌ Gagal kirim ke {user['user_id']}: {e}")
                    # Kalau diblokir user, bisa opsi hapus dari DB (opsional)
            
            # Istirahat Batch (2 menit)
            if i + batch_size < total_users:
                print("☕ Istirahat 2 menit biar aman...")
                await asyncio.sleep(120)
                
        print(f"✅ BROADCAST SELESAI. Terkirim: {sent_count}/{total_users}")
        
    except Exception as e:
        print(f"❌ Error Broadcast Fatal: {e}")
    finally:
        BROADCAST_RUNNING = False

@app.route('/start_broadcast', methods=['POST'])
def start_broadcast():
    global BOT_LOOP, BROADCAST_RUNNING
    
    if BROADCAST_RUNNING:
        return jsonify({"status": "error", "message": "Broadcast sedang berjalan! Tunggu sampai selesai."})
        
    message = request.form.get('message')
    if not message:
        return jsonify({"status": "error", "message": "Pesan tidak boleh kosong!"})
        
    if BOT_LOOP:
        asyncio.run_coroutine_threadsafe(run_broadcast_task(message), BOT_LOOP)
        return jsonify({"status": "success", "message": "Broadcast dimulai di background!"})
    else:
        return jsonify({"status": "error", "message": "Bot belum siap."})

# --- BASIC ROUTES ---
@app.route('/add_schedule', methods=['POST'])
def add_schedule():
    h, m = request.form.get('hour'), request.form.get('minute')
    if h: supabase.table('blast_schedules').insert({"run_hour": int(h), "run_minute": int(m)}).execute()
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
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)

# --- TELETHON LOGIC (UPDATED WITH CRM) ---
@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    if not event.is_private: return
    sender = await event.get_sender()
    if not sender or sender.bot: return
    
    sender_id = sender.id
    now = datetime.now()
    
    # === LOGIC 1: SAVE USER TO SUPABASE (CRM) ===
    # Cek cache lokal dulu biar gak jebol DB
    should_update_db = False
    
    if sender_id not in user_db_cache:
        should_update_db = True
    else:
        # Cek apakah sudah lewat 1 jam dari update terakhir
        if now - user_db_cache[sender_id] > timedelta(hours=DB_UPDATE_INTERVAL_HOURS):
            should_update_db = True
            
    if should_update_db:
        # Jalankan di background task biar gak nge-block reply
        asyncio.create_task(save_user_to_db(sender_id, sender.username, sender.first_name))
        user_db_cache[sender_id] = now # Update cache lokal

    # === LOGIC 2: AUTO REPLY ===
    if sender_id in last_replies:
        if now - last_replies[sender_id] < timedelta(hours=AUTO_REPLY_DELAY_HOURS):
            return
            
    await asyncio.sleep(random.randint(2, 5))
    try:
        await event.reply(AUTO_REPLY_MSG)
        last_replies[sender_id] = now
        print(f"📩 Auto-Reply: {sender.first_name}")
    except: pass

async def save_user_to_db(uid, uname, fname):
    """Upsert User ke Supabase (Insert or Update)"""
    try:
        # Cek user ada atau belum
        res = supabase.table('tele_users').select('user_id').eq('user_id', uid).execute()
        
        data = {
            "user_id": uid,
            "username": uname,
            "first_name": fname,
            "last_interaction": datetime.utcnow().isoformat()
        }
        
        if res.data:
            # Update last interaction
            supabase.table('tele_users').update(data).eq('user_id', uid).execute()
            # print(f"🔄 CRM: User {fname} updated.")
        else:
            # Insert new user
            supabase.table('tele_users').insert(data).execute()
            print(f"🆕 CRM: User Baru Tersimpan! {fname}")
            
    except Exception as e:
        print(f"⚠️ CRM Save Error: {e}")

# --- AUTO BLAST ---
def log_to_db(g_name, g_id, t_id, status, err=""):
    try:
        supabase.table('blast_logs').insert({"group_name": g_name, "group_id": g_id, "topic_id": t_id, "status": status, "error_message": str(err)}).execute()
    except: pass

async def auto_forward():
    print(f"🚀 Userbot Standby. CRM & Panel Ready.")
    last_run_time = None
    while True:
        now = datetime.now()
        cur_time = f"{now.hour}:{now.minute}"
        
        try:
            schedules = supabase.table('blast_schedules').select("*").eq('is_active', True).execute().data
        except: schedules = []

        is_time = False
        for s in schedules:
            if s['run_hour'] == now.hour and s['run_minute'] == now.minute:
                is_time = True; break
        
        if is_time and cur_time != last_run_time:
            print(f"\n--- ⏰ BLASTING START: {cur_time} ---")
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
                        last_run_time = cur_time
            except Exception as e: print(f"Blast Error: {e}")
        await asyncio.sleep(30)

async def start_bot():
    global BOT_LOOP
    BOT_LOOP = asyncio.get_running_loop()
    await client.connect()
    if not await client.is_user_authorized(): return
    print("✅ BOT CONNECTED")
    await auto_forward()

if __name__ == '__main__':
    Thread(target=run_web).start()
    asyncio.run(start_bot())
