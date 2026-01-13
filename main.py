import os
import asyncio
import random
import sys
import json
import logging
from datetime import datetime, timedelta
from threading import Thread
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, jsonify

# --- TELETHON & SUPABASE ---
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from supabase import create_client, Client

# --- KONFIGURASI LOGGING ---
logging.basicConfig(
    format='[%(levelname)s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BabaBot")

# --- LOAD ENVIRONMENT VARIABLES ---
load_dotenv()

# --- KONFIGURASI SUPABASE ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("❌ ERROR: SUPABASE_URL atau SUPABASE_KEY belum diisi di file .env!")
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    logger.critical(f"❌ Gagal koneksi awal ke Supabase: {e}")
    sys.exit(1)

# --- KONFIGURASI TELEGRAM ---
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH')
STRING_SESSION = os.getenv('STRING_SESSION')
SOURCE_CHAT_ID = int(os.getenv('SOURCE_CHAT_ID', '0'))
SOURCE_MSG_ID = int(os.getenv('SOURCE_MSG_ID', '0'))

# --- PENGATURAN BOT ---
# Auto Reply dengan Inline Link (Markdown) - Versi Perfect
AUTO_REPLY_MSG = (
    "Selamat datang di Baba Parfume! ✨\n\n"
    "Lagi cari aroma apa nih kak? Untuk cewe apa cowo? "
    "Kalo belum punya aroma personal, biar mimin bantu rekomendasiin ya ^^\n\n"
    "👇 *Katalog Lengkap & Testimoni:*\n"
    "[KLIK DISINI YA KAK](https://t.me/GantiUsernameChannelMu)"
)
AUTO_REPLY_DELAY_HOURS = 6    # Jeda waktu auto-reply ke user yang sama
DB_UPDATE_INTERVAL_HOURS = 1  # Jeda update data user ke DB
TIMEZONE_OFFSET = 7           # WIB (UTC+7)

# --- GLOBAL VARIABLES ---
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
last_replies = {}    # Cache waktu reply terakhir
user_db_cache = {}   # Cache update DB terakhir
BOT_LOOP = None      # Event Loop Asyncio
BROADCAST_RUNNING = False 

# --- FLASK APP ---
app = Flask(__name__)
app.secret_key = 'baba_parfume_super_secret_key_v3_final'

# ==========================================
# BAGIAN 1: HELPER FUNCTIONS (DATABASE & UTILS)
# ==========================================

def get_wib_time():
    """Mengambil waktu saat ini dalam WIB (UTC+7)."""
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)

def log_to_db(g_name, g_id, t_id, status, err=""):
    """Mencatat log hasil blast ke Supabase."""
    try:
        data = {
            "group_name": g_name,
            "group_id": int(g_id),
            "topic_id": int(t_id) if t_id else None,
            "status": status,
            "error_message": str(err),
            "created_at": get_wib_time().isoformat()
        }
        supabase.table('blast_logs').insert(data).execute()
    except Exception as e:
        logger.error(f"Gagal simpan log DB: {e}")

async def save_user_to_db(uid, uname, fname):
    """Upsert (Update/Insert) User ke CRM Supabase."""
    try:
        # Cek apakah user ada
        res = supabase.table('tele_users').select('user_id').eq('user_id', uid).execute()
        
        data = {
            "user_id": uid,
            "username": uname,
            "first_name": fname,
            "last_interaction": datetime.utcnow().isoformat()
        }
        
        if res.data:
            supabase.table('tele_users').update(data).eq('user_id', uid).execute()
        else:
            supabase.table('tele_users').insert(data).execute()
            logger.info(f"🆕 CRM: User Baru Tersimpan! {fname} ({uid})")
            
    except Exception as e:
        logger.error(f"⚠️ CRM Save Error: {e}")

async def get_entity_safe(entity_id):
    """
    Fungsi SAKTI untuk mencari Entity (User/Grup) dengan aman.
    Mencegah error 'PeerUser/PeerChannel not found'.
    """
    try:
        # 1. Cek Cache Lokal (Cepat)
        return await client.get_input_entity(entity_id)
    except:
        try:
            # 2. Force Fetch dari Server Telegram (Lambat tapi Akurat)
            # logger.info(f"🔍 Fetching entity {entity_id} from network...")
            return await client.get_entity(entity_id)
        except Exception as e:
            logger.error(f"❌ Entity {entity_id} benar-benar tidak ditemukan: {e}")
            return None

# ==========================================
# BAGIAN 2: FLASK ROUTES (WEB DASHBOARD)
# ==========================================

@app.route('/')
def dashboard():
    # 1. Fetch Logs
    try:
        logs = supabase.table('blast_logs').select("*").order('created_at', desc=True).limit(10).execute().data
    except: logs = []

    # 2. Fetch Schedules
    try:
        schedules = supabase.table('blast_schedules').select("*").order('run_hour').execute().data
    except: schedules = []

    # 3. Fetch Targets
    try:
        targets = supabase.table('blast_targets').select("*").order('created_at').execute().data
    except: targets = []
    
    # 4. Count Users
    try:
        user_count = supabase.table('tele_users').select("user_id", count='exact').execute().count
    except: user_count = 0
        
    return render_template('index.html', 
                          logs=logs, 
                          schedules=schedules,
                          targets=targets,
                          user_count=user_count,
                          broadcast_running=BROADCAST_RUNNING)

# --- API: SCAN GROUP ---
async def fetch_telegram_dialogs():
    groups_data = []
    if not client.is_connected(): await client.connect()
    
    logger.info("🔄 Memulai Scan Grup Telegram...")
    # Limit dinaikkan ke 500 agar grup lama terdeteksi
    async for dialog in client.iter_dialogs(limit=500):
        if dialog.is_group:
            entity = dialog.entity
            is_forum = getattr(entity, 'forum', False)
            
            g_data = {
                'id': entity.id, 
                'name': entity.title, 
                'is_forum': is_forum, 
                'topics': []
            }
            
            # Scan Topik jika Forum
            if is_forum:
                try:
                    topics = await client.get_forum_topics(entity, limit=50)
                    if topics and topics.topics:
                        for t in topics.topics:
                            g_data['topics'].append({'id': t.id, 'title': t.title})
                except Exception as e:
                    logger.warning(f"⚠️ Skip topik {entity.title}: {e}")
            
            groups_data.append(g_data)
            
    return groups_data

@app.route('/scan_groups_api')
def scan_groups_api():
    global BOT_LOOP
    try:
        if BOT_LOOP is None: return jsonify({"status": "error", "message": "Bot startup..."})
        future = asyncio.run_coroutine_threadsafe(fetch_telegram_dialogs(), BOT_LOOP)
        return jsonify({"status": "success", "data": future.result(timeout=60)})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

# --- API: SAVE TARGETS ---
@app.route('/save_bulk_targets', methods=['POST'])
def save_bulk_targets():
    try:
        data = request.json
        selected = data.get('targets', [])
        
        for item in selected:
            # Normalisasi input topics (bisa list atau string)
            raw_topics = item.get('topic_ids', [])
            topics_list = []
            
            if isinstance(raw_topics, list):
                topics_list = raw_topics
            elif isinstance(raw_topics, str) and raw_topics.strip():
                topics_list = [t.strip() for t in raw_topics.split(',') if t.strip()]

            topics_str = ", ".join(map(str, topics_list))
            
            # Upsert Target
            payload = {
                "group_name": item['group_name'],
                "group_id": int(item['group_id']),
                "topic_ids": topics_str,
                "is_active": True
            }
            
            exist = supabase.table('blast_targets').select('id').eq('group_id', item['group_id']).execute()
            if exist.data:
                supabase.table('blast_targets').update(payload).eq('group_id', item['group_id']).execute()
            else:
                supabase.table('blast_targets').insert(payload).execute()
                
        return jsonify({"status": "success", "message": "Target berhasil disimpan!"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

# --- API: IMPORT CRM (HISTORY) ---
async def run_import_history_task():
    logger.info("📥 MULAI IMPORT RIWAYAT CHAT (CRM)...")
    count = 0
    try:
        if not client.is_connected(): await client.connect()
        # Scan 2000 dialog personal terakhir
        async for dialog in client.iter_dialogs(limit=2000):
            if dialog.is_user and not dialog.entity.bot:
                user = dialog.entity
                try:
                    await save_user_to_db(user.id, user.username, user.first_name)
                    count += 1
                except Exception as e:
                    logger.error(f"Skip import user {user.id}: {e}")
                
                await asyncio.sleep(0.05) # Rate limit protection
                
        logger.info(f"🎉 IMPORT SELESAI. Total di-scan: {count}")
        return count
    except Exception as e:
        logger.error(f"❌ Import Error: {e}")
        return 0

@app.route('/import_crm_api', methods=['POST'])
def import_crm_api():
    global BOT_LOOP
    if BOT_LOOP:
        asyncio.run_coroutine_threadsafe(run_import_history_task(), BOT_LOOP)
        return jsonify({"status": "success", "message": "Proses Import berjalan di background!"})
    return jsonify({"status": "error", "message": "Bot belum siap."})

# --- API: BROADCAST ---
async def run_broadcast_task(message_text):
    global BROADCAST_RUNNING
    BROADCAST_RUNNING = True
    logger.info("📢 MULAI BROADCAST...")
    
    try:
        response = supabase.table('tele_users').select("user_id, first_name").execute()
        users = response.data
        total_users = len(users)
        sent_count = 0
        batch_size = 50 # Limit aman agar tidak banned
        
        logger.info(f"🎯 Target Broadcast: {total_users} users")

        for i in range(0, total_users, batch_size):
            batch = users[i:i+batch_size]
            logger.info(f"🚀 Batch {i+1} - {i+len(batch)}...")

            for user in batch:
                target_user_id = int(user['user_id'])
                # Gunakan helper get_entity_safe untuk mencegah error PeerUser
                receiver_entity = await get_entity_safe(target_user_id)

                if receiver_entity:
                    try:
                        # Personalisasi nama
                        u_name = user.get('first_name') or "Kak"
                        final_msg = message_text.replace("{name}", u_name)
                        
                        await client.send_message(receiver_entity, final_msg)
                        sent_count += 1
                        
                        # Human Delay Random (Penting!)
                        await asyncio.sleep(random.uniform(2.5, 4.5))
                        
                    except errors.FloodWaitError as e:
                        logger.warning(f"⏳ Kena FloodWait {e.seconds} detik. Tidur dulu...")
                        await asyncio.sleep(e.seconds + 5)
                    except Exception as e:
                        logger.error(f"❌ Gagal kirim ke {target_user_id}: {e}")
            
            # Istirahat Panjang antar Batch
            if i + batch_size < total_users:
                logger.info("☕ Istirahat 2 menit (Anti-Ban)...")
                await asyncio.sleep(120)

        logger.info(f"✅ BROADCAST SELESAI. Terkirim: {sent_count}/{total_users}")

    except Exception as e:
        logger.error(f"❌ Error Broadcast Fatal: {e}")
    finally:
        BROADCAST_RUNNING = False

@app.route('/start_broadcast', methods=['POST'])
def start_broadcast():
    global BOT_LOOP, BROADCAST_RUNNING
    if BROADCAST_RUNNING: return jsonify({"status": "error", "message": "Broadcast sedang berjalan!"})
    
    message = request.form.get('message')
    if not message: return jsonify({"status": "error", "message": "Pesan kosong!"})
    
    if BOT_LOOP:
        asyncio.run_coroutine_threadsafe(run_broadcast_task(message), BOT_LOOP)
        return jsonify({"status": "success", "message": "Broadcast dimulai!"})
    return jsonify({"status": "error", "message": "Bot belum siap."})

# --- CRUD JADWAL & TARGET ---
@app.route('/add_schedule', methods=['POST'])
def add_schedule():
    h, m = request.form.get('hour'), request.form.get('minute')
    if h: supabase.table('blast_schedules').insert({"run_hour": int(h), "run_minute": int(m), "is_active": True}).execute()
    return redirect(url_for('dashboard'))

@app.route('/delete_schedule/<int:id>')
def delete_schedule(id):
    supabase.table('blast_schedules').delete().eq('id', id).execute()
    return redirect(url_for('dashboard'))

@app.route('/delete_target/<int:id>')
def delete_target(id):
    supabase.table('blast_targets').delete().eq('id', id).execute()
    return redirect(url_for('dashboard'))

# ==========================================
# BAGIAN 3: TELEGRAM BOT LOGIC (ASYNC)
# ==========================================

@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    """Menangani pesan masuk untuk CRM & Auto-Reply"""
    if not event.is_private: return # Hanya private chat
    
    sender = await event.get_sender()
    if not sender or sender.bot: return # Abaikan pesan dari bot lain
    
    sender_id = sender.id
    now = datetime.now()
    
    # 1. CRM Save (Dengan Cache Memory)
    should_update_db = False
    if sender_id not in user_db_cache: 
        should_update_db = True
    elif now - user_db_cache[sender_id] > timedelta(hours=DB_UPDATE_INTERVAL_HOURS): 
        should_update_db = True
            
    if should_update_db:
        asyncio.create_task(save_user_to_db(sender_id, sender.username, sender.first_name))
        user_db_cache[sender_id] = now 

    # 2. Auto Reply
    if sender_id in last_replies:
        # Jika belum lewat jeda waktu auto-reply, jangan balas lagi
        if now - last_replies[sender_id] < timedelta(hours=AUTO_REPLY_DELAY_HOURS): 
            return
    
    # Typing effect simulation
    async with client.action(sender_id, 'typing'):
        await asyncio.sleep(random.randint(2, 4))
        
    try:
        await event.reply(AUTO_REPLY_MSG, link_preview=True)
        last_replies[sender_id] = now
        logger.info(f"📩 Auto-Reply terkirim ke: {sender.first_name}")
    except Exception as e:
        logger.error(f"Gagal Auto-Reply: {e}")

async def auto_blast_loop():
    """Loop Utama untuk Auto Blast Terjadwal (WIB) - MAXIMIZED VERSION"""
    logger.info(f"🚀 Blast Service Standby. Mode: WIB (UTC+{TIMEZONE_OFFSET})")
    last_run_time_str = None
    
    while True:
        # --- SAFETY 1: CHECK CONNECTION ---
        if not client.is_connected():
            logger.warning("🔌 Koneksi terputus. Mencoba connect ulang...")
            try: await client.connect()
            except: pass

        # Hitung waktu WIB sekarang
        wib_now = get_wib_time()
        cur_time_str = f"{wib_now.hour}:{wib_now.minute}"
        
        # Cek database jadwal
        try: 
            schedules = supabase.table('blast_schedules').select("*").eq('is_active', True).execute().data
        except: 
            schedules = []
            await asyncio.sleep(10) # Jeda jika DB error

        is_scheduled = False
        for s in schedules:
            if s['run_hour'] == wib_now.hour and s['run_minute'] == wib_now.minute: 
                is_scheduled = True; break
        
        # Eksekusi jika waktunya pas dan belum dieksekusi menit ini
        if is_scheduled and cur_time_str != last_run_time_str:
            logger.info(f"\n--- ⏰ JADWAL BLAST DIEKSEKUSI (WIB): {cur_time_str} ---")
            
            if SOURCE_CHAT_ID == 0 or SOURCE_MSG_ID == 0:
                logger.error("❌ SOURCE_CHAT_ID atau SOURCE_MSG_ID belum diset di .env")
            else:
                # --- SAFETY 2: PREPARE SOURCE ENTITY ---
                # Pastikan bot mengenali sumber pesan (Chat ID/Saved Messages)
                source_entity = await get_entity_safe(SOURCE_CHAT_ID)
                
                if not source_entity:
                    logger.error(f"❌ Gagal Blast: Source Chat ID {SOURCE_CHAT_ID} tidak ditemukan/bot lupa. Coba pancing chat.")
                    # Skip putaran ini, tapi set last_run biar ga spam error tiap detik
                    last_run_time_str = cur_time_str 
                else:
                    try:
                        targets = supabase.table('blast_targets').select("*").eq('is_active', True).execute().data
                        
                        if targets:
                            # Ambil objek pesan asli
                            msg_source = await client.get_messages(source_entity, ids=SOURCE_MSG_ID)
                            
                            if msg_source:
                                random.shuffle(targets) # Acak urutan biar natural
                                
                                for target in targets:
                                    # Parsing Topic IDs
                                    raw_topics = target.get('topic_ids', '')
                                    t_ids = [int(x.strip()) for x in raw_topics.split(',') if x.strip().isdigit()] if raw_topics else [None]
                                    
                                    # --- SAFETY 3: PREPARE TARGET ENTITY ---
                                    # Pastikan bot mengenali Grup Tujuan
                                    target_group_id = target['group_id']
                                    target_entity = await get_entity_safe(target_group_id)

                                    if not target_entity:
                                        err_msg = f"Bot tidak mengenali Grup ID {target_group_id}. Coba pancing dengan chat manual."
                                        log_to_db(target['group_name'], target_group_id, 0, "FAILED", err_msg)
                                        continue
                                    
                                    for t_id in t_ids:
                                        try:
                                            # PENGIRIMAN:
                                            await client.send_message(
                                                target_entity, 
                                                msg_source, 
                                                reply_to=t_id
                                            )
                                            
                                            log_to_db(target['group_name'], target['group_id'], t_id, "SUCCESS")
                                            logger.info(f"✅ Sent to {target['group_name']} (Topic: {t_id})")
                                            
                                            # Delay antar grup/topik
                                            await asyncio.sleep(random.randint(45, 90))
                                            
                                        except errors.FloodWaitError as e:
                                            logger.warning(f"⏳ Kena FloodWait saat Blast {e.seconds} detik...")
                                            log_to_db(target['group_name'], target['group_id'], t_id, "FLOODWAIT", f"Wait {e.seconds}s")
                                            await asyncio.sleep(e.seconds + 5)

                                        except Exception as e:
                                            err_msg = str(e)
                                            log_to_db(target['group_name'], target['group_id'], t_id, "FAILED", err_msg)
                                            logger.error(f"❌ Failed {target['group_name']}: {err_msg}")
                                
                                # Update penanda waktu
                                last_run_time_str = cur_time_str
                            else:
                                logger.error("⚠️ Pesan Sumber (Source Message) tidak ditemukan atau terhapus!")
                        else:
                            logger.warning("⚠️ Tidak ada target grup aktif di Database.")
                            
                    except Exception as e:
                        logger.error(f"❌ Blast Error Fatal: {e}")
        
        # Cek setiap 20 detik
        await asyncio.sleep(20)

async def start_bot():
    global BOT_LOOP
    BOT_LOOP = asyncio.get_running_loop()
    
    try:
        await client.start()
        logger.info("✅ TELEGRAM CLIENT CONNECTED & AUTHORIZED")
        # Jalankan loop blast
        await auto_blast_loop()
    except Exception as e:
        logger.critical(f"❌ Gagal start bot: {e}")

def run_web():
    port = int(os.getenv("PORT", 8080))
    # use_reloader=False penting agar thread tidak double
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)

if __name__ == '__main__':
    # Jalankan Flask di Thread terpisah
    t = Thread(target=run_web)
    t.start()
    
    # Jalankan Asyncio Loop di Main Thread
    asyncio.run(start_bot())
