import os
import asyncio
import random
import sys
import json
import logging
import platform
import time
from datetime import datetime, timedelta
from threading import Thread
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, jsonify

# --- TELETHON & SUPABASE ---
from telethon import TelegramClient, events, errors, utils, functions, types
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel, PeerUser
from supabase import create_client, Client

# ==========================================
# KONFIGURASI SISTEM & LOGGING
# ==========================================

# Format logging yang lebih detail untuk debugging level dewa
logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Opsional: FileHandler jika ingin menyimpan log ke file
        # logging.FileHandler("bot_activity.log") 
    ]
)
logger = logging.getLogger("BabaBot_Ultimate")

# Load Environment Variables
load_dotenv()

# ==========================================
# KONFIGURASI DATABASE (SUPABASE)
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.critical("❌ FATAL ERROR: SUPABASE_URL atau SUPABASE_KEY hilang! Cek file .env Anda.")
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Koneksi Supabase Berhasil Diinisialisasi.")
except Exception as e:
    logger.critical(f"❌ Gagal koneksi awal ke Supabase: {e}")
    sys.exit(1)

# ==========================================
# KONFIGURASI TELEGRAM CLIENT
# ==========================================
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH')
STRING_SESSION = os.getenv('STRING_SESSION')
SOURCE_CHAT_ID = int(os.getenv('SOURCE_CHAT_ID', '0')) # ID Admin/Sumber
SOURCE_MSG_ID = int(os.getenv('SOURCE_MSG_ID', '0'))

if API_ID == 0 or not API_HASH or not STRING_SESSION:
    logger.critical("❌ FATAL ERROR: Konfigurasi Telegram (API_ID/HASH/SESSION) belum lengkap!")
    sys.exit(1)

# ==========================================
# SETTINGAN FITUR BOT (CUSTOMIZABLE)
# ==========================================
AUTO_REPLY_MSG = (
    "Selamat datang di Baba Parfume! ✨\n\n"
    "Lagi cari aroma apa nih kak? Untuk cewe apa cowo? "
    "Kalo belum punya aroma personal, biar mimin bantu rekomendasiin ya ^^\n\n"
    "👇 *Katalog Lengkap & Testimoni:*\n"
    "[KLIK DISINI YA KAK](https://babaparfume.netlify.app)"
)
AUTO_REPLY_DELAY_HOURS = 6     # Jeda waktu auto-reply ke user yang sama agar tidak spam
DB_UPDATE_INTERVAL_HOURS = 1   # Jeda update data user ke DB (CRM optimization)
TIMEZONE_OFFSET = 7            # WIB (UTC+7)
LOG_RETENTION_DAYS = 7         # Berapa hari log disimpan di DB sebelum dihapus otomatis

# ==========================================
# GLOBAL VARIABLES & STATE MANAGEMENT
# ==========================================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# Cache Memory untuk mengurangi beban Database
last_replies = {}     # Format: {user_id: datetime}
user_db_cache = {}    # Format: {user_id: datetime}
start_time = time.time() # Untuk menghitung Uptime

# Event Loop Reference
BOT_LOOP = None

# Broadcast Flags
BROADCAST_RUNNING = False 

# Blast State Machine (Advanced Control)
# Options: IDLE, RUNNING, PAUSED, STOPPED
BLAST_STATE = "IDLE" 

# Metadata Blast Realtime
BLAST_META = {
    "total_targets": 0,
    "current_index": 0,
    "current_group": "-",
    "success_count": 0,
    "fail_count": 0,
    "last_error": "",
    "start_time": None
}

# ==========================================
# FLASK WEB SERVER (BACKEND DASHBOARD)
# ==========================================
app = Flask(__name__)
app.secret_key = 'baba_parfume_super_secret_key_v4_ultimate_gacor'

# --- ROUTE: PING (KEEP ALIVE) ---
@app.route('/ping')
def ping():
    """Endpoint untuk Uptime Robot agar bot tidak tidur."""
    uptime_seconds = int(time.time() - start_time)
    uptime_str = str(timedelta(seconds=uptime_seconds))
    
    return jsonify({
        "status": "online",
        "message": "Pong! 🏓",
        "app": "BabaBot Ultimate",
        "uptime": uptime_str,
        "blast_state": BLAST_STATE,
        "server_time": datetime.utcnow().isoformat()
    }), 200

# --- ROUTE: DASHBOARD UTAMA ---
@app.route('/')
def dashboard():
    # 1. Fetch Logs Terakhir
    try: 
        logs = supabase.table('blast_logs').select("*").order('created_at', desc=True).limit(10).execute().data
    except Exception as e: 
        logger.error(f"Dashboard Log Error: {e}")
        logs = []

    # 2. Fetch Jadwal
    try: 
        schedules = supabase.table('blast_schedules').select("*").order('run_hour').execute().data
    except: schedules = []

    # 3. Fetch Target
    try: 
        targets = supabase.table('blast_targets').select("*").order('created_at').execute().data
    except: targets = []
    
    # 4. Count Users CRM
    try: 
        user_count = supabase.table('tele_users').select("user_id", count='exact').execute().count
    except: user_count = 0
        
    return render_template('index.html', 
                           logs=logs, 
                           schedules=schedules,
                           targets=targets,
                           user_count=user_count,
                           broadcast_running=BROADCAST_RUNNING,
                           blast_state=BLAST_STATE,
                           blast_meta=BLAST_META)

# --- API CONTROL BLAST ---
@app.route('/api/blast/control', methods=['POST'])
def blast_control():
    global BLAST_STATE, BLAST_META
    action = request.json.get('action')
    
    if action == 'start':
        if BLAST_STATE in ['IDLE', 'STOPPED']:
            BLAST_STATE = 'RUNNING'
            BLAST_META['start_time'] = datetime.now().isoformat()
            return jsonify({"status": "success", "message": "🚀 Blast Dimulai!"})
        elif BLAST_STATE == 'PAUSED':
            BLAST_STATE = 'RUNNING'
            return jsonify({"status": "success", "message": "▶️ Blast Dilanjutkan!"})
            
    elif action == 'pause':
        if BLAST_STATE == 'RUNNING':
            BLAST_STATE = 'PAUSED'
            return jsonify({"status": "success", "message": "⏸️ Blast Dipause."})
            
    elif action == 'stop':
        BLAST_STATE = 'STOPPED'
        return jsonify({"status": "success", "message": "🛑 Blast Dihentikan Paksa!"})
        
    return jsonify({"status": "error", "message": "Action tidak valid"})

@app.route('/api/blast/status')
def blast_status_api():
    return jsonify({
        "state": BLAST_STATE,
        "meta": BLAST_META,
        "broadcast_running": BROADCAST_RUNNING
    })

# --- API SCAN GROUP ---
async def fetch_telegram_dialogs():
    """Fungsi scan grup dengan penanganan error tingkat tinggi."""
    groups_data = []
    if not client.is_connected(): await client.connect()
    
    logger.info("🔄 Memulai Deep Scan Grup Telegram...")
    try:
        async for dialog in client.iter_dialogs(limit=600): # Limit ditingkatkan
            if dialog.is_group:
                entity = dialog.entity
                is_forum = getattr(entity, 'forum', False)
                real_id = utils.get_peer_id(entity)
                
                g_data = {
                    'id': real_id, 
                    'name': entity.title, 
                    'is_forum': is_forum, 
                    'topics': []
                }
                
                # Fitur Scan Topic Forum
                if is_forum:
                    try:
                        # Mengambil topic aktif
                        topics = await client.get_forum_topics(entity, limit=30)
                        if topics and topics.topics:
                            for t in topics.topics:
                                g_data['topics'].append({'id': t.id, 'title': t.title})
                    except Exception as e:
                        logger.warning(f"⚠️ Gagal fetch topik untuk {entity.title}: {e}")
                
                groups_data.append(g_data)
    except Exception as e:
        logger.error(f"❌ Error saat scanning dialog: {e}")
            
    return groups_data

@app.route('/scan_groups_api')
def scan_groups_api():
    global BOT_LOOP
    try:
        if BOT_LOOP is None: return jsonify({"status": "error", "message": "Bot sedang inisialisasi..."})
        future = asyncio.run_coroutine_threadsafe(fetch_telegram_dialogs(), BOT_LOOP)
        return jsonify({"status": "success", "data": future.result(timeout=120)})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

# --- API SAVE TARGETS ---
@app.route('/save_bulk_targets', methods=['POST'])
def save_bulk_targets():
    try:
        data = request.json
        selected = data.get('targets', [])
        success_count = 0
        
        for item in selected:
            # Normalisasi Input Topic IDs
            raw_topics = item.get('topic_ids', [])
            topics_list = []
            
            if isinstance(raw_topics, list):
                topics_list = raw_topics
            elif isinstance(raw_topics, str) and raw_topics.strip():
                topics_list = [t.strip() for t in raw_topics.split(',') if t.strip()]

            topics_str = ", ".join(map(str, topics_list))
            
            payload = {
                "group_name": item['group_name'],
                "group_id": int(item['group_id']),
                "topic_ids": topics_str,
                "is_active": True
            }
            
            # Upsert Logic
            exist = supabase.table('blast_targets').select('id').eq('group_id', item['group_id']).execute()
            if exist.data:
                supabase.table('blast_targets').update(payload).eq('group_id', item['group_id']).execute()
            else:
                supabase.table('blast_targets').insert(payload).execute()
            success_count += 1
                
        return jsonify({"status": "success", "message": f"{success_count} Target berhasil disimpan!"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

# --- API IMPORT CRM ---
async def run_import_history_task():
    logger.info("📥 MULAI IMPORT RIWAYAT CHAT (CRM)...")
    count = 0
    try:
        if not client.is_connected(): await client.connect()
        # Scan history lebih dalam (3000 dialog)
        async for dialog in client.iter_dialogs(limit=3000):
            if dialog.is_user and not dialog.entity.bot:
                user = dialog.entity
                try:
                    await save_user_to_db(user.id, user.username, user.first_name)
                    count += 1
                except Exception as e:
                    pass # Silent fail untuk speed
                
                await asyncio.sleep(0.01) # Micro sleep
                
        logger.info(f"🎉 IMPORT SELESAI. Total User CRM: {count}")
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

# --- API BROADCAST (SAFE MODE) ---
async def run_broadcast_task(message_text):
    global BROADCAST_RUNNING
    BROADCAST_RUNNING = True
    logger.info("📢 MULAI BROADCAST (Safe Mode)...")
    
    try:
        response = supabase.table('tele_users').select("user_id, first_name").execute()
        users = response.data
        total_users = len(users)
        sent_count = 0
        batch_size = 40 # Limit diturunkan sedikit agar lebih aman
        
        logger.info(f"🎯 Target Broadcast: {total_users} users")

        for i in range(0, total_users, batch_size):
            batch = users[i:i+batch_size]
            logger.info(f"🚀 Batch {i+1} - {i+len(batch)}...")

            for user in batch:
                target_user_id = int(user['user_id'])
                receiver_entity = await get_entity_safe(target_user_id)

                if receiver_entity:
                    try:
                        u_name = user.get('first_name') or "Kak"
                        final_msg = message_text.replace("{name}", u_name)
                        
                        await client.send_message(receiver_entity, final_msg)
                        sent_count += 1
                        
                        # Human Delay Random (Variasi lebih natural)
                        await asyncio.sleep(random.uniform(3.0, 6.0))
                        
                    except errors.FloodWaitError as e:
                        logger.warning(f"⏳ FloodWait {e.seconds}s. Tidur sebentar...")
                        await asyncio.sleep(e.seconds + 10)
                    except errors.UserIsBlockedError:
                        logger.warning(f"🚫 User {target_user_id} memblokir bot.")
                    except Exception as e:
                        logger.error(f"❌ Gagal kirim ke {target_user_id}: {e}")
            
            # Istirahat Panjang antar Batch
            if i + batch_size < total_users:
                logger.info("☕ Istirahat 2.5 menit (Anti-Ban Protocol)...")
                await asyncio.sleep(150)

        logger.info(f"✅ BROADCAST SELESAI. Terkirim: {sent_count}/{total_users}")
        
        # Lapor ke Admin jika broadcast selesai
        if SOURCE_CHAT_ID:
            await send_admin_report(f"✅ **Laporan Broadcast**\n\nTotal Target: {total_users}\nBerhasil: {sent_count}\nStatus: Selesai")

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

# --- CRUD ROUTING ---
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
# BAGIAN 3: UTILITIES & HELPER FUNCTIONS
# ==========================================

def get_wib_time():
    """Helper waktu WIB yang akurat."""
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)

async def send_admin_report(message):
    """Mengirim pesan laporan ke Admin Bot."""
    if not SOURCE_CHAT_ID: return
    try:
        admin_entity = await get_entity_safe(SOURCE_CHAT_ID)
        if admin_entity:
            await client.send_message(admin_entity, message)
    except Exception as e:
        logger.warning(f"Gagal lapor admin: {e}")

def log_to_db(g_name, g_id, t_id, status, err=""):
    """Logger ke Database Supabase."""
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
    """CRM Saver dengan Error Handling."""
    try:
        res = supabase.table('tele_users').select('user_id').eq('user_id', uid).execute()
        data = {
            "user_id": uid, "username": uname, "first_name": fname,
            "last_interaction": datetime.utcnow().isoformat()
        }
        if res.data:
            supabase.table('tele_users').update(data).eq('user_id', uid).execute()
        else:
            supabase.table('tele_users').insert(data).execute()
            logger.info(f"🆕 CRM: +1 User ({fname})")
    except Exception as e:
        logger.error(f"⚠️ CRM Save Error: {e}")

async def get_entity_safe(entity_id, force_network=False):
    """
    Entity Resolver Canggih (Ultimate Version).
    Mencoba berbagai metode untuk mendapatkan entity Telegram yang valid.
    """
    entity_id = int(entity_id)
    
    # 1. Cache/Local Input
    if not force_network:
        try: return await client.get_input_entity(entity_id)
        except: pass
        try:
            if entity_id > 0: return await client.get_input_entity(int(f"-100{entity_id}"))
        except: pass

    # 2. Network Fetch (Heavy but Accurate)
    try: return await client.get_entity(entity_id)
    except: pass
    
    try:
        if entity_id > 0: return await client.get_entity(int(f"-100{entity_id}"))
    except Exception as e:
        logger.debug(f"Entity Resolver Failed for {entity_id}: {e}")
        return None

# ==========================================
# BAGIAN 4: BACKGROUND TASKS & HEARTBEAT
# ==========================================

async def auto_cleanup_logs():
    """Tugas pembersihan log database otomatis (Maintenance)."""
    while True:
        try:
            # Hitung tanggal batas (7 hari lalu)
            cutoff_date = (datetime.utcnow() - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
            
            # Hapus log lama
            supabase.table('blast_logs').delete().lt('created_at', cutoff_date).execute()
            logger.info(f"🧹 Database Maintenance: Log < {LOG_RETENTION_DAYS} hari dihapus.")
            
        except Exception as e:
            logger.error(f"Cleanup Error: {e}")
            
        # Jalan setiap 24 jam
        await asyncio.sleep(86400)

async def system_heartbeat():
    """
    Jantung Utama Aplikasi.
    Melakukan ping internal dan menjaga sesi Telegram tetap hidup.
    """
    logger.info("💓 Heartbeat Service Started.")
    while True:
        try:
            uptime = str(timedelta(seconds=int(time.time() - start_time)))
            logger.info(f"💓 Heartbeat Tick | Uptime: {uptime} | State: {BLAST_STATE}")
            
            # Self-Ping Telegram (Kirim 'typing' action ke Saved Messages agar dianggap aktif)
            if client.is_connected():
                try:
                    await client.send_read_acknowledge("me")
                    # Opsional: Kirim typing action
                    # await client(functions.messages.SetTypingRequest(
                    #     peer=types.InputPeerSelf(),
                    #     action=types.SendMessageTypingAction()
                    # ))
                except: pass
                
        except Exception as e:
            logger.error(f"Heartbeat Glitch: {e}")
        
        # Berdetak setiap 5 menit
        await asyncio.sleep(300)

# ==========================================
# BAGIAN 5: TELEGRAM BOT LOGIC (CORE)
# ==========================================

# --- ADMIN COMMANDS HANDLER (NEW FEATURE) ---
@client.on(events.NewMessage(incoming=True, from_users=[SOURCE_CHAT_ID]))
async def handle_admin_commands(event):
    """
    Menangani Perintah Admin via Telegram.
    Hanya merespon pesan dari SOURCE_CHAT_ID (Admin).
    """
    global BLAST_STATE
    msg = event.message.message.strip().lower()
    
    if msg == '/ping':
        await event.reply("🏓 **Pong!**\nSystem Online & Gacor!\n\nUse `/status` to check details.")
        
    elif msg == '/status':
        uptime = str(timedelta(seconds=int(time.time() - start_time)))
        stats = (
            f"🤖 **BABA BOT STATUS**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔌 Connection: `Connected`\n"
            f"⏱ Uptime: `{uptime}`\n"
            f"📡 Blast State: `{BLAST_STATE}`\n"
            f"🎯 Success: `{BLAST_META['success_count']}`\n"
            f"❌ Failed: `{BLAST_META['fail_count']}`\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        await event.reply(stats)
        
    elif msg == '/pause':
        if BLAST_STATE == 'RUNNING':
            BLAST_STATE = 'PAUSED'
            await event.reply("⏸️ Blast di-pause sementara.")
        else:
            await event.reply("⚠️ Bot tidak sedang berjalan.")
            
    elif msg == '/resume':
        if BLAST_STATE == 'PAUSED':
            BLAST_STATE = 'RUNNING'
            await event.reply("▶️ Blast dilanjutkan!")
        else:
            await event.reply("⚠️ Bot tidak dalam status Pause.")
            
    elif msg == '/stop':
        BLAST_STATE = 'STOPPED'
        await event.reply("🛑 Blast dihentikan paksa (Hard Stop).")
        
    elif msg == '/help':
        help_text = (
            "🛠 **ADMIN COMMANDS**\n"
            "`/ping` - Cek hidup/mati\n"
            "`/status` - Cek statistik blast\n"
            "`/pause` - Jeda blast sementara\n"
            "`/resume` - Lanjut blast\n"
            "`/stop` - Matikan blast\n"
        )
        await event.reply(help_text)

# --- PUBLIC MESSAGE HANDLER (AUTO REPLY & CRM) ---
@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    if not event.is_private: return # Hanya private chat
    
    sender = await event.get_sender()
    if not sender or sender.bot: return
    
    sender_id = sender.id
    now = datetime.now()
    
    # 1. CRM Save Logic
    should_update_db = False
    if sender_id not in user_db_cache: 
        should_update_db = True
    elif now - user_db_cache[sender_id] > timedelta(hours=DB_UPDATE_INTERVAL_HOURS): 
        should_update_db = True
            
    if should_update_db:
        # Jalankan di background task agar tidak blocking
        asyncio.create_task(save_user_to_db(sender_id, sender.username, sender.first_name))
        user_db_cache[sender_id] = now 

    # 2. Auto Reply Logic
    # Jangan reply admin jika admin sedang nge-command
    if sender_id == SOURCE_CHAT_ID and event.message.message.startswith('/'):
        return

    if sender_id in last_replies:
        if now - last_replies[sender_id] < timedelta(hours=AUTO_REPLY_DELAY_HOURS): 
            return
    
    # Typing Simulation
    async with client.action(sender_id, 'typing'):
        await asyncio.sleep(random.randint(2, 4))
        
    try:
        await event.reply(AUTO_REPLY_MSG, link_preview=True)
        last_replies[sender_id] = now
        logger.info(f"📩 Auto-Reply: {sender.first_name}")
    except Exception as e:
        logger.error(f"Gagal Auto-Reply: {e}")

# --- CORE BLAST LOOP ---
async def auto_blast_loop():
    """
    Mesin Utama Blast dengan Logic Terpadu.
    Menangani Jadwal, Antrian, Retry, dan State Machine.
    """
    global BLAST_STATE, BLAST_META
    logger.info(f"🚀 Blast Engine Started. Mode: WIB (UTC+{TIMEZONE_OFFSET})")
    last_run_time_str = None
    
    while True:
        # Check Connection Integrity
        if not client.is_connected():
            logger.warning("🔌 Koneksi Telegram terputus, reconnecting...")
            try: await client.connect()
            except: pass

        # === SCHEDULER LOGIC ===
        wib_now = get_wib_time()
        cur_time_str = f"{wib_now.hour}:{wib_now.minute}"
        
        try: 
            schedules = supabase.table('blast_schedules').select("*").eq('is_active', True).execute().data
        except: 
            schedules = []
            await asyncio.sleep(10) # Safety delay

        is_scheduled = False
        for s in schedules:
            if s['run_hour'] == wib_now.hour and s['run_minute'] == wib_now.minute: 
                is_scheduled = True; break
        
        # Trigger Auto-Start by Schedule
        if is_scheduled and cur_time_str != last_run_time_str and BLAST_STATE == 'IDLE':
            logger.info(f"⏰ JADWAL MATCH: {cur_time_str} - Memulai Blast...")
            BLAST_STATE = 'RUNNING'
            BLAST_META['start_time'] = datetime.now().isoformat()
            last_run_time_str = cur_time_str
            await send_admin_report(f"⏰ **Jadwal Blast Dimulai!**\nWaktu: {cur_time_str} WIB")
            
        # === STATE MACHINE PROCESSING ===
        if BLAST_STATE == 'RUNNING':
            # 1. Pre-Flight Checks
            if SOURCE_CHAT_ID == 0 or SOURCE_MSG_ID == 0:
                logger.error("❌ Config SOURCE_CHAT_ID/MSG_ID Invalid.")
                BLAST_STATE = 'STOPPED'
                continue
                
            source_entity = await get_entity_safe(SOURCE_CHAT_ID)
            if not source_entity:
                logger.error("❌ Source Entity Not Found.")
                BLAST_STATE = 'STOPPED'
                continue
                
            targets = supabase.table('blast_targets').select("*").eq('is_active', True).execute().data
            if not targets:
                logger.warning("⚠️ Target Kosong.")
                BLAST_STATE = 'IDLE'
                continue

            # 2. Prepare Meta Data
            if BLAST_META['current_index'] == 0:
                random.shuffle(targets) # Randomize for safety
                BLAST_META['total_targets'] = len(targets)
                BLAST_META['success_count'] = 0
                BLAST_META['fail_count'] = 0
                
            msg_source = await client.get_messages(source_entity, ids=SOURCE_MSG_ID)
            if not msg_source:
                logger.error("❌ Pesan Sumber Hilang/Terhapus.")
                BLAST_STATE = 'STOPPED'
                continue

            # 3. Processing Loop
            while BLAST_META['current_index'] < len(targets):
                
                # Dynamic Control Check
                if BLAST_STATE == 'PAUSED':
                    await asyncio.sleep(2)
                    continue
                if BLAST_STATE == 'STOPPED':
                    break 
                
                target = targets[BLAST_META['current_index']]
                BLAST_META['current_group'] = target['group_name']
                
                # Parse Topics
                raw_topics = target.get('topic_ids', '')
                t_ids = [int(x.strip()) for x in raw_topics.split(',') if x.strip().isdigit()] if raw_topics else [None]
                target_group_id = target['group_id']

                # Topic Loop
                for t_id in t_ids:
                    while BLAST_STATE == 'PAUSED': await asyncio.sleep(1)
                    if BLAST_STATE == 'STOPPED': break

                    # Entity Resolution
                    target_entity = await get_entity_safe(target_group_id)

                    if not target_entity:
                        log_to_db(target['group_name'], target_group_id, 0, "FAILED", "Invalid Entity")
                        BLAST_META['fail_count'] += 1
                        continue

                    try:
                        # SENDING ACTION
                        await client.send_message(
                            target_entity, 
                            msg_source, 
                            reply_to=t_id
                        )
                        
                        log_to_db(target['group_name'], target['group_id'], t_id, "SUCCESS")
                        BLAST_META['success_count'] += 1
                        logger.info(f"✅ Sent: {target['group_name']}")
                        
                        # Smart Delay (45s - 90s)
                        await asyncio.sleep(random.randint(45, 90))
                        
                    except errors.FloodWaitError as e:
                        logger.warning(f"⏳ FloodWait: {e.seconds}s")
                        log_to_db(target['group_name'], target['group_id'], t_id, "FLOODWAIT", f"Wait {e.seconds}s")
                        await asyncio.sleep(e.seconds + 5)

                    except Exception as e:
                        err_str = str(e)
                        
                        # Smart Retry Strategy
                        if "Invalid Peer" in err_str or "PEER_ID_INVALID" in err_str:
                            logger.info("🔄 Retry with Force Network Fetch...")
                            fresh_entity = await get_entity_safe(target_group_id, force_network=True)
                            if fresh_entity:
                                try:
                                    await client.send_message(fresh_entity, msg_source, reply_to=t_id)
                                    log_to_db(target['group_name'], target_group_id, t_id, "SUCCESS (RETRY)")
                                    BLAST_META['success_count'] += 1
                                except Exception as e2:
                                    log_to_db(target['group_name'], target['group_id'], t_id, "FAILED", str(e2))
                                    BLAST_META['fail_count'] += 1
                            else:
                                BLAST_META['fail_count'] += 1
                        else:
                            log_to_db(target['group_name'], target['group_id'], t_id, "FAILED", err_str)
                            BLAST_META['fail_count'] += 1

                BLAST_META['current_index'] += 1
            
            # 4. Finish Handling
            if BLAST_STATE == 'STOPPED':
                logger.info("🛑 Blast Stopped by User.")
                BLAST_META['current_index'] = 0
                BLAST_STATE = 'IDLE'
                await send_admin_report("🛑 **Blast Dihentikan Paksa**")
            else:
                logger.info("✅ Blast Job Completed.")
                BLAST_STATE = 'IDLE'
                BLAST_META['current_index'] = 0
                # Lapor hasil ke admin
                report = (
                    f"✅ **Blast Selesai!**\n\n"
                    f"Total: {BLAST_META['total_targets']}\n"
                    f"Sukses: {BLAST_META['success_count']}\n"
                    f"Gagal: {BLAST_META['fail_count']}"
                )
                await send_admin_report(report)
                
        elif BLAST_STATE == 'STOPPED':
            BLAST_META['current_index'] = 0
            BLAST_STATE = 'IDLE'
        
        # Idle Tick
        if BLAST_STATE == 'IDLE':
             await asyncio.sleep(20)
        else:
             await asyncio.sleep(1)

# ==========================================
# SYSTEM ENTRY POINT
# ==========================================

async def start_bot():
    global BOT_LOOP
    BOT_LOOP = asyncio.get_running_loop()
    
    try:
        await client.start()
        logger.info("✅ TELEGRAM CLIENT CONNECTED & AUTHORIZED")
        
        # Jalankan Background Service
        asyncio.create_task(system_heartbeat())    # Anti-Tidur
        asyncio.create_task(auto_cleanup_logs())   # Database Cleaner
        
        if SOURCE_CHAT_ID:
            await send_admin_report("🖥 **Bot System Online**\nVersi: Ultimate Edition\nStatus: Ready")
            
        # Jalankan Core Loop
        await auto_blast_loop()
        
    except Exception as e:
        logger.critical(f"❌ Gagal start bot: {e}")

def run_web():
    """Menjalankan Flask Server di Thread terpisah."""
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)

if __name__ == '__main__':
    print(r"""
    ____  ___  ____  ___    ____  ____  ______
   / __ )/   |/ __ )/   |  / __ )/ __ \/_  __/
  / __  / /| / __  / /| | / __  / / / / / /   
 / /_/ / ___/ /_/ / ___ |/ /_/ / /_/ / / /    
/_____/_/  /_____/_/  |_/_____/\____/ /_/     
    ULTIMATE EDITION - GACOR MODE ON 🚀
    """)
    
    # 1. Jalankan Web Server
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
    
    # 2. Jalankan Asyncio Loop (Bot Telegram)
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("Shutdown...")
