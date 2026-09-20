import os
import sqlite3
import secrets
import threading
import time
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8652721295:AAFr2bbnGN8W0K5TucPiAxGkUgY_weCPZWw")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "7296733212")
API_SECRET = os.environ.get("API_SECRET", "maxtube-api-2026-secret-X9K2M")
PORT = int(os.environ.get("PORT", 5000))

# ══════════════════════════════════════════════════════════════════
# DATABASE PATH - بێ global, بێ کێشە
# ══════════════════════════════════════════════════════════════════
def get_db_path():
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        return "/data/maxtube.db"
    return "maxtube.db"

DB_PATH = get_db_path()

# Rate limit
RATE_LIMIT = {}
RATE_MAX = 15
RATE_WINDOW = 60

# ══════════════════════════════════════════════════════════════════
# FLASK
# ══════════════════════════════════════════════════════════════════
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)


# ══════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
        print(f"✅ Database initialized at: {DB_PATH}")
    except Exception as e:
        print(f"❌ DB init error: {e}")


def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
        print(f"⚠️ Log error: {e}")


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
def send_telegram(text, chat_id=None, keyboard=None, parse_mode="HTML"):
    if chat_id is None:
        chat_id = ADMIN_CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard) if isinstance(keyboard, dict) else keyboard
        r = requests.post(url, json=payload, timeout=15)
        return r.json()
    except Exception as e:
        print(f"⚠️ Telegram error: {e}")
        return None


def answer_callback(callback_id, text="✅"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        requests.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=5)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════
def rate_limit_check(ip):
    now = time.time()
    if ip not in RATE_LIMIT:
        RATE_LIMIT[ip] = []
    RATE_LIMIT[ip] = [t for t in RATE_LIMIT[ip] if now - t < RATE_WINDOW]
    if len(RATE_LIMIT[ip]) >= RATE_MAX:
        return False
    RATE_LIMIT[ip].append(now)
    return True


def gen_key_string(key_type):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    def part():
        return ''.join(secrets.choice(chars) for _ in range(4))
    type_code = {
        'PRO-MAX': 'PRM', 'PREMIUM': 'VIP', 'LIMITED': 'LMT',
        'MAX': 'MAX', 'TRIAL': 'TRL', 'LIFETIME': 'LFE'
    }.get(key_type, 'GEN')
    year = datetime.now().year
    return f"MAXTUBE-{type_code}-{year}-{part()}-{part()}"


# ══════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════
@app.route('/')
def index():
    try:
        return send_from_directory('.', 'index.html')
    except Exception:
        return jsonify({"name": "MaxTube Pro MAX", "status": "running"})


@app.route('/api/health')
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.now().isoformat(),
        "db": "connected" if os.path.exists(DB_PATH) else "missing"
    })


@app.route('/api/activate', methods=['POST'])
def api_activate():
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
        ua = request.headers.get('User-Agent', 'Unknown')[:200]
        data = request.get_json() or {}
        key = (data.get('key') or '').strip().upper()

        if not rate_limit_check(ip):
            send_telegram(f"🚨 <b>RATE LIMIT!</b>\n🌐 {ip}")
            return jsonify({"success": False, "error": "Too many requests"}), 429

        if not key:
            return jsonify({"success": False, "error": "No key"}), 400

        conn = db()
        row = conn.execute("SELECT * FROM keys WHERE key = ?", (key,)).fetchone()

        conn.execute(
            "INSERT INTO activations (key, ip, user_agent, success, created_at) VALUES (?,?,?,?,?)",
            (key, ip, ua, 1 if row and row['status'] == 'active' else 0, datetime.now().isoformat())
        )
        conn.commit()

        if not row:
            conn.close()
            log_event("activate_fail_notfound", ip, ua, key)
            send_telegram(
                f"❌ <b>کلیلا نەدروست!</b>\n\n"
                f"🔑 <code>{key}</code>\n"
                f"🌐 <code>{ip}</code>\n"
                f"🖥️ <code>{ua[:150]}</code>"
            )
            return jsonify({"success": False, "error": "کلیل نەدروست"})

        if row['status'] == 'revoked':
            conn.close()
            send_telegram(f"🚫 <b>کلیلا ناچالاک!</b>\n🔑 <code>{key}</code>")
            return jsonify({"success": False, "error": "کلیل ناچالاک"})

        conn.execute(
            "UPDATE keys SET status='used', used_at=?, used_by_ip=?, used_by_ua=? WHERE key=?",
            (datetime.now().isoformat(), ip, ua, key)
        )
        conn.commit()
        conn.close()

        log_event("activate_success", ip, ua, key)
        send_telegram(
            f"✅ <b>کلیلا چالاک هاتە بکارئینان!</b>\n\n"
            f"🔑 <code>{key}</code>\n"
            f"📅 <b>{row['type']}</b> • {row['days']} ڕۆژ\n"
            f"🌐 <code>{ip}</code>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return jsonify({"success": True, "type": row['type'], "days": row['days']})

    except Exception as e:
        print(f"❌ activate error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/log', methods=['POST'])
def api_log():
    try:
        data = request.get_json() or {}
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
        ua = request.headers.get('User-Agent', 'Unknown')[:200]
        log_event(data.get('event', 'unknown'), ip, ua, data.get('info', {}))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/stats')
def api_stats():
    try:
        if request.headers.get('X-API-Secret') != API_SECRET:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        conn = db()
        total = conn.execute("SELECT COUNT(*) as c FROM keys").fetchone()['c']
        active = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='active'").fetchone()['c']
        used = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='used'").fetchone()['c']
        revoked = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='revoked'").fetchone()['c']
        activations = conn.execute("SELECT COUNT(*) as c FROM activations").fetchone()['c']
        conn.close()
        return jsonify({
            "success": True, "total": total, "active": active,
            "used": used, "revoked": revoked, "activations": activations
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# BOT MENUS
# ══════════════════════════════════════════════════════════════════
def bot_send_main_menu(chat_id):
    kb = {
        "inline_keyboard": [
            [{"text": "🔑 دروستکرنا کلیلێ", "callback_data": "menu_newkey"}],
            [{"text": "📋 لیستا کلیلان", "callback_data": "menu_listkeys"}],
            [{"text": "📊 ئامار", "callback_data": "menu_stats"}],
            [{"text": "📜 لۆگان", "callback_data": "menu_logs"}]
        ]
    }
    send_telegram(
        "🛡️ <b>MaxTube Pro MAX - داشبۆردا ئەدمینی</b>\n\n"
        "بەخێربێی ئەدمین! 👋",
        chat_id, kb
    )


def bot_send_key_types(chat_id):
    kb = {
        "inline_keyboard": [
            [{"text": "👑 PRO MAX (365 ڕۆژ)", "callback_data": "gentype_PRO-MAX_365"}],
            [{"text": "💎 PREMIUM (180 ڕۆژ)", "callback_data": "gentype_PREMIUM_180"}],
            [{"text": "⚡ LIMITED (90 ڕۆژ)", "callback_data": "gentype_LIMITED_90"}],
            [{"text": "🔥 MAX (30 ڕۆژ)", "callback_data": "gentype_MAX_30"}],
            [{"text": "🎁 TRIAL (7 ڕۆژ)", "callback_data": "gentype_TRIAL_7"}],
            [{"text": "🏆 LIFE-TIME", "callback_data": "gentype_LIFETIME_9999"}],
            [{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]
        ]
    }
    send_telegram("🔑 <b>جۆرێ کلیلێ هەلبژێرە:</b>", chat_id, kb)


def bot_generate_key(chat_id, key_type, days):
    try:
        key = gen_key_string(key_type)
        conn = db()
        attempts = 0
        while conn.execute("SELECT 1 FROM keys WHERE key=?", (key,)).fetchone() and attempts < 100:
            key = gen_key_string(key_type)
            attempts += 1

        conn.execute(
            "INSERT INTO keys (key, type, days, status, created_at) VALUES (?,?,?,?,?)",
            (key, key_type, days, 'active', datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        kb = {
            "inline_keyboard": [
                [{"text": "🔑 کلیلەکا دی", "callback_data": "menu_newkey"}],
                [{"text": "⬅️ مینویا سەرەکی", "callback_data": "menu_back"}]
            ]
        }
        send_telegram(
            f"✅ <b>کلیلا نوی!</b>\n\n"
            f"🔑 <code>{key}</code>\n\n"
            f"📅 <b>{key_type}</b>\n"
            f"⏱️ <b>{days} ڕۆژ</b>",
            chat_id, kb
        )
    except Exception as e:
        send_telegram(f"❌ خودان: {e}", chat_id)


def bot_list_keys(chat_id):
    try:
        conn = db()
        rows = conn.execute("SELECT * FROM keys ORDER BY id DESC LIMIT 20").fetchall()
        conn.close()

        if not rows:
            send_telegram(
                "📋 چ کلیل نینە",
                chat_id,
                {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]}
            )
            return

        text = "📋 <b>کلیل (20):</b>\n\n"
        for r in rows:
            icon = {"active": "🟢", "used": "🟡", "revoked": "🔴"}.get(r['status'], "⚪")
            text += f"{icon} <code>{r['key']}</code>\n"
            text += f"    └ {r['type']} • {r['days']}d\n\n"

        send_telegram(
            text, chat_id,
            {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]}
        )
    except Exception as e:
        send_telegram(f"❌ {e}", chat_id)


def bot_stats(chat_id):
    try:
        conn = db()
        total = conn.execute("SELECT COUNT(*) as c FROM keys").fetchone()['c']
        active = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='active'").fetchone()['c']
        used = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='used'").fetchone()['c']
        revoked = conn.execute("SELECT COUNT(*) as c FROM keys WHERE status='revoked'").fetchone()['c']
        acts = conn.execute("SELECT COUNT(*) as c FROM activations").fetchone()['c']
        conn.close()

        send_telegram(
            f"📊 <b>ئامار</b>\n\n"
            f"🔑 کۆما: <b>{total}</b>\n"
            f"🟢 چالاک: <b>{active}</b>\n"
            f"🟡 بکارهێنرن: <b>{used}</b>\n"
            f"🔴 ناچالاک: <b>{revoked}</b>\n"
            f"📈 چالاککرن: <b>{acts}</b>",
            chat_id,
            {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]}
        )
    except Exception as e:
        send_telegram(f"❌ {e}", chat_id)


def bot_logs(chat_id):
    try:
        conn = db()
        rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 15").fetchall()
        conn.close()

        if not rows:
            send_telegram("📜 چ لۆگ نینە", chat_id)
            return

        text = "📜 <b>لۆگ:</b>\n\n"
        for r in rows:
            text += f"• <b>{r['event']}</b> — {r['ip'] or '-'}\n"

        send_telegram(
            text, chat_id,
            {"inline_keyboard": [[{"text": "⬅️ پاشەوە", "callback_data": "menu_back"}]]}
        )
    except Exception as e:
        send_telegram(f"❌ {e}", chat_id)


# ══════════════════════════════════════════════════════════════════
# BOT HANDLER
# ══════════════════════════════════════════════════════════════════
def handle_update(update):
    try:
        if "callback_query" in update:
            cq = update["callback_query"]
            chat_id = str(cq["message"]["chat"]["id"])
            data = cq.get("data", "")
            cb_id = cq["id"]

            if chat_id != ADMIN_CHAT_ID:
                answer_callback(cb_id, "❌ نە ئەدمین")
                send_telegram(f"🚨 هەوڵدانا دەستگەهشتنا بۆتێ!\nChat ID: <code>{chat_id}</code>")
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
            elif data == "menu_back":
                bot_send_main_menu(chat_id)
            elif data.startswith("gentype_"):
                parts = data.replace("gentype_", "").rsplit("_", 1)
                if len(parts) == 2:
                    bot_generate_key(chat_id, parts[0], int(parts[1]))
            return

        if "message" not in update:
            return
        msg = update["message"]
        chat_id = str(msg["chat"]["id"])
        text = (msg.get("text") or "").strip()

        if chat_id != ADMIN_CHAT_ID:
            send_telegram(f"🚨 هەوڵدان!\nChat ID: <code>{chat_id}</code>\n💬 {text[:100]}")
            send_telegram("⛔ تە ئەدمین نینی!", chat_id)
            return

        if text in ("/start", "/menu"):
            bot_send_main_menu(chat_id)
        elif text == "/newkey":
            bot_send_key_types(chat_id)
        elif text == "/keys":
            bot_list_keys(chat_id)
        elif text == "/stats":
            bot_stats(chat_id)
        elif text == "/logs":
            bot_logs(chat_id)
        elif text.startswith("/revoke "):
            key = text.replace("/revoke ", "").strip().upper()
            conn = db()
            r = conn.execute("UPDATE keys SET status='revoked' WHERE key=?", (key,))
            conn.commit()
            conn.close()
            send_telegram(f"🚫 ناچالاک: <code>{key}</code>" if r.rowcount else f"❌ نەهاتە دیتن", chat_id)
        elif text.startswith("/delete "):
            key = text.replace("/delete ", "").strip().upper()
            conn = db()
            r = conn.execute("DELETE FROM keys WHERE key=?", (key,))
            conn.commit()
            conn.close()
            send_telegram(f"🗑️ ژێبری: <code>{key}</code>" if r.rowcount else f"❌ نەهاتە دیتن", chat_id)
        elif text.startswith("/find "):
            key = text.replace("/find ", "").strip().upper()
            conn = db()
            r = conn.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
            conn.close()
            if r:
                send_telegram(
                    f"🔍 <code>{r['key']}</code>\n"
                    f"📅 {r['type']}\n⏱️ {r['days']}d\n📊 {r['status']}",
                    chat_id
                )
            else:
                send_telegram(f"❌ نەهاتە دیتن", chat_id)
        else:
            send_telegram(f"❓ <code>{text}</code>", chat_id)

    except Exception as e:
        print(f"❌ handle_update: {e}")


# ══════════════════════════════════════════════════════════════════
# POLLING
# ══════════════════════════════════════════════════════════════════
def bot_polling():
    print("🤖 Bot polling started...")
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
    except Exception:
        pass
    time.sleep(2)

    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            r = requests.get(url, params={"timeout": 30, "offset": last_update_id + 1}, timeout=35)
            data = r.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    handle_update(update)
        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"⚠️ Polling: {e}")
            time.sleep(5)


# ══════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════
def startup():
    print("=" * 60)
    print("🚀 MaxTube Pro MAX Starting")
    print("=" * 60)
    print(f"📁 DB: {DB_PATH}")
    print(f"🌐 Port: {PORT}")
    print(f"👤 Admin: {ADMIN_CHAT_ID}")
    print("=" * 60)

    init_db()
    threading.Thread(target=bot_polling, daemon=True).start()

    send_telegram(
        f"🚀 <b>MaxTube Pro MAX هاتە دەستپێکرن!</b>\n\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 /stats"
    )
    print("✅ Ready!")


if __name__ == "__main__":
    startup()
    print(f"🌐 Flask on 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
