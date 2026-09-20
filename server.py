"""
MaxTube Pro MAX - Backend Server + Telegram Bot
سیستەمێ ئەدمینی ب تەلەگرامی
"""
import os
import sqlite3
import secrets
import hashlib
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

# ============================================================
# ⚙️ ڕێکخستن - CONFIG
# ============================================================
BOT_TOKEN = "8652721295:AAFr2bbnGN8W0K5TucPiAxGkUgY_weCPZWw"
ADMIN_CHAT_ID = "7296733212"
ADMIN_PASSWORD = "MaxTube@2026"  # پاسوۆردا ئەدمینی ل سەر بۆت
API_SECRET = "maxtube-api-2026-secret-X9K2M"  # بگوهۆڕە!
DB_PATH = "maxtube.db"

# Rate limiting
RATE_LIMIT = {}  # {ip: [timestamps]}
RATE_MAX = 10  # 10 داخواز د 1 خولەکێ دا
RATE_WINDOW = 60

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# ============================================================
# 🗄️ داتابەیس
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        days INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        used_at TEXT,
        used_by_ip TEXT,
        used_by_ua TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT,
        data TEXT,
        created_at TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS activations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT,
        success INTEGER,
        created_at TEXT NOT NULL
    )''')
    conn.commit()
    conn.close()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def log_event(event, ip=None, ua=None, data=None):
    try:
        conn = db()
        conn.execute(
            "INSERT INTO logs (event, ip, user_agent, data, created_at) VALUES (?,?,?,?,?)",
            (event, ip, ua, str(data) if data else None, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Log error: {e}")

# ============================================================
# 📤 تەلەگرام - SEND
# ============================================================
def send_telegram(text, chat_id=ADMIN_CHAT_ID, keyboard=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

def answer_callback(callback_id, text="✅"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        requests.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=5)
    except Exception as e:
        print(f"Callback error: {e}")

def edit_message(chat_id, message_id, text, keyboard=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Edit error: {e}")

# ============================================================
# 🎯 API ROUTES
# ============================================================
def rate_limit_check(ip):
    now = time.time()
    if ip not in RATE_LIMIT:
        RATE_LIMIT[ip] = []
    RATE_LIMIT[ip] = [t for t in RATE_LIMIT[ip] if now - t < RATE_WINDOW]
    if len(RATE_LIMIT[ip]) >= RATE_MAX:
        return False
    RATE_LIMIT[ip].append(now)
    return True

def check_api_secret():
    secret = request.headers.get('X-API-Secret') or request.json.get('secret') if request.is_json else None
    return secret == API_SECRET

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/activate', methods=['POST'])
def api_activate():
    """چالاککرنا کلیلێ - ئاگەهداری بۆ تەلەگرامی"""
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        ua = request.headers.get('User-Agent', 'Unknown')
        data = request.get_json() or {}
        key = (data.get('key') or '').strip().upper()

        if not rate_limit_check(ip):
            send_telegram(
                f"🚨 <b>RATE LIMIT EXCEEDED!</b>\n"
                f"🌐 IP: <code>{ip}</code>\n"
                f"🖥️ UA: <code>{ua[:100]}</code>\n"
                f"⚠️ داخوازا زێدە ل سەر هێژمارێ!"
            )
            return jsonify({"success": False, "error": "Too many requests"}), 429

        if not key:
            return jsonify({"success": False, "error": "No key provided"}), 400

        conn = db()
        row = conn.execute("SELECT * FROM keys WHERE key = ?", (key,)).fetchone()

        # تۆمارکرنا هەر داخوازەکێ چالاککرنێ
        conn.execute(
            "INSERT INTO activations (key, ip, user_agent, success, created_at) VALUES (?,?,?,?,?)",
            (key, ip, ua[:200], 1 if row and row['status'] == 'active' else 0, datetime.now().isoformat())
        )
        conn.commit()

        if not row:
            conn.close()
            log_event("activate_fail_notfound", ip, ua, key)
            send_telegram(
                f"❌ <b>کلیلا نەدروست - هەوڵدانا چالاککرنێ</b>\n\n"
                f"🔑 کلیل: <code>{key}</code>\n"
                f"🌐 IP: <code>{ip}</code>\n"
                f"🖥️ User-Agent: <code>{ua[:150]}</code>\n"
                f"🕐 دەم: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
                f"⚠️ ئەڤ کلیلە د داتابەیسێ دا نینە!"
            )
            return jsonify({"success": False, "error": "کلیل نەدروست"})

        if row['status'] == 'revoked':
            conn.close()
            log_event("activate_fail_revoked", ip, ua, key)
            send_telegram(
                f"🚫 <b>کلیلا ناچالاک - هەوڵدانا بکارئینانێ</b>\n\n"
                f"🔑 کلیل: <code>{key}</code>\n"
                f"📅 جۆر: {row['type']}\n"
                f"🌐 IP: <code>{ip}</code>\n"
                f"🖥️ UA: <code>{ua[:150]}</code>\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return jsonify({"success": False, "error": "کلیل ناچالاک کرێیە"})

        # چالاک - نیشانکرن وەک بکارهێنرای
        conn.execute(
            "UPDATE keys SET status='used', used_at=?, used_by_ip=?, used_by_ua=? WHERE key=?",
            (datetime.now().isoformat(), ip, ua[:200], key)
        )
        conn.commit()
        conn.close()

        log_event("activate_success", ip, ua, key)
        send_telegram(
            f"✅ <b>کلیلا چالاک هاتە بکارئینان!</b>\n\n"
            f"🔑 کلیل: <code>{key}</code>\n"
            f"📅 جۆر: <b>{row['type']}</b>\n"
            f"⏱️ دووماهی: <b>{row['days']} ڕۆژ</b>\n"
            f"🌐 IP: <code>{ip}</code>\n"
            f"🖥️ User-Agent: <code>{ua[:150]}</code>\n"
            f"🕐 دەم: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
        )
        return jsonify({"success": True, "type": row['type'], "days": row['days']})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/log', methods=['POST'])
def api_log():
    """تۆمارکرنا هەمی ئاکتیڤیتییان"""
    try:
        data = request.get_json() or {}
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        ua = request.headers.get('User-Agent', 'Unknown')
        event = data.get('event', 'unknown')
        info = data.get('info', {})

        log_event(event, ip, ua, info)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/health')
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# ============================================================
# 🤖 TELEGRAM BOT - COMMANDS
# ============================================================
def gen_key_string(key_type):
    """دروستکرنا کلیلێ ب فۆرماتێ تایبەت"""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part = lambda: ''.join(secrets.choice(chars) for _ in range(4))
    type_code = {
        'PRO-MAX': 'PRM', 'PREMIUM': 'VIP', 'LIMITED': 'LMT',
        'MAX': 'MAX', 'TRIAL': 'TRL', 'LIFETIME': 'LFE'
    }.get(key_type, 'GEN')
    return f"MAXTUBE-{type_code}-{datetime.now().year}-{part()}-{part()}"

def bot_send_main_menu(chat_id):
    """مینویا سەرەکی"""
    kb = {
        "inline_keyboard": [
            [{"text": "🔑 دروستکرنا کلیلێ", "callback_data": "menu_newkey"}],
            [{"text": "📋 لیستا کلیلان", "callback_data": "menu_listkeys"}],
            [{"text": "📊 ئامار", "callback_data": "menu_stats"}],
            [{"text": "📜 لۆگان", "callback_data": "menu_logs"}],
            [{"text": "❓ یارمەتی", "callback_data": "menu_help"}]
        ]
    }
    send_telegram(
        "🛡️ <b>MaxTube Pro MAX - داشبۆردا ئەدمینی</b>\n\n"
        "بەخێربێی ئەدمین!\n"
        "هەلبژێرە:",
        chat_id, kb
    )

def bot_send_key_types(chat_id):
    """جۆرێن کلیلان"""
    kb = {
        "inline_keyboard": [
            [{"text": "👑 PRO MAX (ساڵانە - 365 ڕۆژ)", "callback_data": "gentype_PRO-MAX_365"}],
            [{"text": "💎 PREMIUM (٦ مانگ - 180 ڕۆژ)", "callback_data": "gentype_PREMIUM_180"}],
            [{"text": "⚡ LIMITED (٣ مانگ - 90 ڕۆژ)", "callback_data": "gentype_LIMITED_90"}],
            [{"text": "🔥 MAX (١ مانگ - 30 ڕۆژ)", "callback_data": "gentype_MAX_30"}],
            [{"text": "🎁 TRIAL (٧ ڕۆژ)", "callback_data": "gentype_TRIAL_7"}],
            [{"text": "🏆 LIFE-TIME (ئەبەدی)", "callback_data": "gentype_LIFETIME_9999"}],
            [{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]
        ]
    }
    send_telegram("🔑 <b>جۆرێ کلیلێ هەلبژێرە:</b>", chat_id, kb)

def bot_generate_key(chat_id, key_type, days):
    """دروستکرنا کلیلێ و ناردن"""
    key = gen_key_string(key_type)
    # دڵنیابوون ژ دووبارەبوونێ
    conn = db()
    while conn.execute("SELECT 1 FROM keys WHERE key=?", (key,)).fetchone():
        key = gen_key_string(key_type)

    conn.execute(
        "INSERT INTO keys (key, type, days, status, created_at) VALUES (?,?,?,?,?)",
        (key, key_type, days, 'active', datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    log_event("admin_new_key", data={"key": key, "type": key_type, "days": days})

    kb = {
        "inline_keyboard": [
            [{"text": "📋 کۆپیکرنا کلیلێ", "callback_data": f"copy_{key}"}],
            [{"text": "🔑 کلیلەکا دی دروست بکە", "callback_data": "menu_newkey"}],
            [{"text": "⬅️ مینویا سەرەکی", "callback_data": "menu_back"}]
        ]
    }
    send_telegram(
        f"✅ <b>کلیلا نوی هاتە دروستکرن!</b>\n\n"
        f"🔑 <code>{key}</code>\n\n"
        f"📅 جۆر: <b>{key_type}</b>\n"
        f"⏱️ دووماهی: <b>{days} ڕۆژ</b>\n"
        f"🕐 دەم: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>",
        chat_id, kb
    )

def bot_list_keys(chat_id):
    """لیستا کلیلان"""
    conn = db()
    rows = conn.execute(
        "SELECT * FROM keys ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    if not rows:
        send_telegram("📋 <b>چ کلیل نینە</b>\n\nل سەرەوە کلیلەکێ دروست بکە.", chat_id,
                      {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]})
        return

    text = "📋 <b>کلیلێن نوهەرترین (20):</b>\n\n"
    for r in rows:
        status_icon = {"active": "🟢", "used": "🟡", "revoked": "🔴"}.get(r['status'], "⚪")
        text += f"{status_icon} <code>{r['key']}</code>\n"
        text += f"    └ {r['type']} • {r['days']}d • {r['status']}\n\n"

    send_telegram(text, chat_id,
                  {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]})

def bot_stats(chat_id):
    """ئامار"""
    conn = db()
    total = conn.execute("SELECT COUNT(*) as c FROM keys").fetchone()['c']
    active = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='active'").fetchone()['c']
    used = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='used'").fetchone()['c']
    revoked = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='revoked'").fetchone()['c']
    activations = conn.execute("SELECT COUNT(*) as c FROM activations").fetchone()['c']
    fails = conn.execute("SELECT COUNT(*) as c FROM activations WHERE success=0").fetchone()['c']
    conn.close()

    send_telegram(
        f"📊 <b>ئامارا سیستەمی</b>\n\n"
        f"🔑 کۆما کلیلان: <b>{total}</b>\n"
        f"🟢 چالاک: <b>{active}</b>\n"
        f"🟡 بکارهێنرن: <b>{used}</b>\n"
        f"🔴 ناچالاک: <b>{revoked}</b>\n\n"
        f"📈 کۆما چالاککرنان: <b>{activations}</b>\n"
        f"❌ شکست: <b>{fails}</b>",
        chat_id,
        {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]}
    )

def bot_logs(chat_id):
    """لۆگان"""
    conn = db()
    rows = conn.execute(
        "SELECT * FROM logs ORDER BY id DESC LIMIT 15"
    ).fetchall()
    conn.close()

    if not rows:
        send_telegram("📜 چ لۆگ نینە", chat_id,
                      {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]})
        return

    text = "📜 <b>لۆگێن نوهەرترین:</b>\n\n"
    for r in rows:
        text += f"• <b>{r['event']}</b>\n"
        text += f"  🌐 {r['ip'] or '-'}\n"
        text += f"  🕐 {r['created_at'][:19]}\n\n"

    send_telegram(text, chat_id,
                  {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]})

# ============================================================
# 🤖 TELEGRAM BOT - POLLING
# ============================================================
def handle_update(update):
    """پڕۆسێسکرنا هەر ئەپدەیتەکێ تەلەگرامی"""
    try:
        # Callback Query (کلیک ل سەر دوگمە)
        if "callback_query" in update:
            cq = update["callback_query"]
            chat_id = str(cq["message"]["chat"]["id"])
            msg_id = cq["message"]["message_id"]
            data = cq.get("data", "")
            cb_id = cq["id"]

            # پشکنینا ئەدمینی
            if chat_id != ADMIN_CHAT_ID:
                answer_callback(cb_id, "❌ تە ئەدمین نینی!")
                send_telegram(
                    f"🚨 <b>هەوڵدانا دەستگەهشتنا بۆتێ!</b>\n\n"
                    f"👤 Chat ID: <code>{chat_id}</code>\n"
                    f"📛 ناڤ: {cq['from'].get('first_name','?')}\n"
                    f"🆔 Username: @{cq['from'].get('username','-')}\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                return

            answer_callback(cb_id, "✅")

            if data == "menu_newkey":
                bot_send_key_types(chat_id)
            elif data == "menu_listkeys":
                bot_list_keys(chat_id)
            elif data == "menu_stats":
                bot_stats(chat_id)
            elif data == "menu_logs":
                bot_logs(chat_id)
            elif data == "menu_help":
                send_telegram(
                    "❓ <b>یارمەتی</b>\n\n"
                    "🔹 /start - مینویا سەرەکی\n"
                    "🔹 /newkey - دروستکرنا کلیلێ\n"
                    "🔹 /keys - لیستا کلیلان\n"
                    "🔹 /stats - ئامار\n"
                    "🔹 /logs - لۆگان\n"
                    "🔹 /revoke KEY - ناچالاککرنا کلیلێ\n"
                    "🔹 /delete KEY - ژێبرنا کلیلێ\n"
                    "🔹 /find KEY - لێگەریان\n",
                    chat_id,
                    {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]}
                )
            elif data == "menu_back":
                bot_send_main_menu(chat_id)
            elif data.startswith("gentype_"):
                parts = data.replace("gentype_", "").rsplit("_", 1)
                if len(parts) == 2:
                    bot_generate_key(chat_id, parts[0], int(parts[1]))
            elif data.startswith("copy_"):
                key = data.replace("copy_", "")
                answer_callback(cb_id, f"📋 کلیل: {key}")
            elif data.startswith("revoke_"):
                key = data.replace("revoke_", "")
                conn = db()
                conn.execute("UPDATE keys SET status='revoked' WHERE key=?", (key,))
                conn.commit()
                conn.close()
                send_telegram(f"🚫 کلیل هاتە ناچالاککرن:\n<code>{key}</code>", chat_id)
            elif data.startswith("delete_"):
                key = data.replace("delete_", "")
                conn = db()
                conn.execute("DELETE FROM keys WHERE key=?", (key,))
                conn.commit()
                conn.close()
                send_telegram(f"🗑️ کلیل هاتە ژێبرن:\n<code>{key}</code>", chat_id)
            return

        # Message (کۆماند)
        if "message" not in update:
            return
        msg = update["message"]
        chat_id = str(msg["chat"]["id"])
        text = (msg.get("text") or "").strip()
        from_user = msg.get("from", {})

        # پشکنینا ئەدمینی
        if chat_id != ADMIN_CHAT_ID:
            send_telegram(
                f"🚨 <b>هەوڵدانا دەستگەهشتنا بۆتێ!</b>\n\n"
                f"👤 Chat ID: <code>{chat_id}</code>\n"
                f"📛 ناڤ: {from_user.get('first_name','?')}\n"
                f"🆔 @{from_user.get('username','-')}\n"
                f"💬 نامە: <code>{text[:100]}</code>\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            send_telegram("⛔ تە دەستگەهشت ب ڤی بۆتی نینە!", chat_id)
            return

        # کۆماندێن ئەدمینی
        if text == "/start" or text == "/menu":
            bot_send_main_menu(chat_id)
        elif text == "/newkey":
            bot_send_key_types(chat_id)
        elif text == "/keys":
            bot_list_keys(chat_id)
        elif text == "/stats":
            bot_stats(chat_id)
        elif text == "/logs":
            bot_logs(chat_id)
        elif text == "/help":
            send_telegram(
                "❓ <b>کۆماندێن بەردەست:</b>\n\n"
                "/start - مینویا سەرەکی\n"
                "/newkey - دروستکرنا کلیلێ\n"
                "/keys - لیستا کلیلان\n"
                "/stats - ئامار\n"
                "/logs - لۆگان\n"
                "/revoke KEY - ناچالاککرنا کلیلێ\n"
                "/delete KEY - ژێبرنا کلیلێ\n"
                "/find KEY - لێگەریان",
                chat_id
            )
        elif text.startswith("/revoke "):
            key = text.replace("/revoke ", "").strip().upper()
            conn = db()
            r = conn.execute("UPDATE keys SET status='revoked' WHERE key=?", (key,))
            conn.commit()
            conn.close()
            if r.rowcount:
                send_telegram(f"🚫 کلیل هاتە ناچالاککرن:\n<code>{key}</code>", chat_id)
            else:
                send_telegram(f"❌ کلیل نەهاتە دیتن:\n<code>{key}</code>", chat_id)
        elif text.startswith("/delete "):
            key = text.replace("/delete ", "").strip().upper()
            conn = db()
            r = conn.execute("DELETE FROM keys WHERE key=?", (key,))
            conn.commit()
            conn.close()
            if r.rowcount:
                send_telegram(f"🗑️ کلیل هاتە ژێبرن:\n<code>{key}</code>", chat_id)
            else:
                send_telegram(f"❌ کلیل نەهاتە دیتن:\n<code>{key}</code>", chat_id)
        elif text.startswith("/find "):
            key = text.replace("/find ", "").strip().upper()
            conn = db()
            r = conn.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
            conn.close()
            if r:
                send_telegram(
                    f"🔍 <b>کلیل هاتە دیتن:</b>\n\n"
                    f"🔑 <code>{r['key']}</code>\n"
                    f"📅 {r['type']}\n"
                    f"⏱️ {r['days']}d\n"
                    f"📊 دۆخ: {r['status']}\n"
                    f"🕐 دروستکرن: {r['created_at'][:19]}\n"
                    f"👤 بکارهێنەر: {r['used_by_ip'] or '-'}",
                    chat_id
                )
            else:
                send_telegram(f"❌ نەهاتە دیتن: <code>{key}</code>", chat_id)
        else:
            send_telegram(f"❓ کۆماندا نەناسراو: <code>{text}</code>\n/help بنێرە.", chat_id)
    except Exception as e:
        print(f"Handle update error: {e}")

def bot_polling():
    """پۆلینگا تەلەگرامی - د Threadەکێ دا"""
    print("🤖 Bot polling started...")
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"timeout": 30, "offset": last_update_id + 1}
            r = requests.get(url, params=params, timeout=35)
            data = r.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    handle_update(update)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)

# ============================================================
# 🚀 START
# ============================================================
if __name__ == "__main__":
    init_db()
    # ناردنا پەیاما چالاکبوونێ
    send_telegram(
        f"🚀 <b>MaxTube Pro MAX هاتە دەستپێکرن!</b>\n\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"✅ سیستەم چالاکە\n"
        f"📊 /stats ببینە"
    )
    # دەستپێکرنا بۆت د Threadەکێ دا
    threading.Thread(target=bot_polling, daemon=True).start()
    # دەستپێکرنا Flask
    print("🌐 Server starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
