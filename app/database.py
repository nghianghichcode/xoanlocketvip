import os
import sqlite3
import uuid
from datetime import datetime, timedelta

try:
    import psycopg
except ImportError:
    psycopg = None


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_NAME = "bot_data.db"
USING_POSTGRES = bool(DATABASE_URL)


def _connect():
    if USING_POSTGRES:
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set but psycopg is not installed")
        return psycopg.connect(DATABASE_URL)
    return sqlite3.connect(DB_NAME)


def _sql(statement):
    """Convert SQLite placeholders to psycopg placeholders."""
    return statement.replace("?", "%s") if USING_POSTGRES else statement


def init_db():
    request_id = "BIGSERIAL PRIMARY KEY" if USING_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS usage_logs (
                        user_id BIGINT,
                        date TEXT,
                        count INTEGER,
                        PRIMARY KEY (user_id, date)
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS referral_bonus_logs (
                        user_id BIGINT,
                        date TEXT,
                        count INTEGER,
                        PRIMARY KEY (user_id, date)
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS ip_usage (
                        ip TEXT,
                        week_start TEXT,
                        count INTEGER,
                        PRIMARY KEY (ip, week_start)
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS ip_unlocks (
                        ip TEXT PRIMARY KEY,
                        unlocked_until TEXT
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS payment_orders (
                        order_id TEXT PRIMARY KEY,
                        ip TEXT,
                        device_key TEXT,
                        amount INTEGER,
                        status TEXT,
                        created_at TEXT,
                        paid_at TEXT,
                        expires_at TEXT,
                        payment_url TEXT
                    )""")
        if USING_POSTGRES:
            c.execute("ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS device_key TEXT")
        else:
            c.execute("PRAGMA table_info(payment_orders)")
            if "device_key" not in {row[1] for row in c.fetchall()}:
                c.execute("ALTER TABLE payment_orders ADD COLUMN device_key TEXT")
        c.execute("""CREATE TABLE IF NOT EXISTS payment_transactions (
                        transaction_id TEXT PRIMARY KEY,
                        order_id TEXT NOT NULL,
                        received_amount INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS device_week_usage (
                        device_key TEXT,
                        week_start TEXT,
                        count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (device_key, week_start)
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS device_unlocks (
                        device_key TEXT PRIMARY KEY,
                        unlocked_until TEXT NOT NULL,
                        allowance INTEGER NOT NULL,
                        used INTEGER NOT NULL DEFAULT 0,
                        source TEXT
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS device_referrals (
                        referral_code TEXT PRIMARY KEY,
                        device_key TEXT UNIQUE NOT NULL
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS device_referral_claims (
                        referral_code TEXT,
                        referred_device TEXT,
                        claimed_at TEXT NOT NULL,
                        PRIMARY KEY (referral_code, referred_device)
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_settings (
                        user_id BIGINT PRIMARY KEY,
                        language TEXT
                    )""")
        c.execute("""CREATE TABLE IF NOT EXISTS bot_config (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )""")
        c.execute(f"""CREATE TABLE IF NOT EXISTS request_logs (
                        id {request_id},
                        user_id BIGINT,
                        uid TEXT,
                        status TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )""")
        conn.commit()
    finally:
        conn.close()


def get_week_start(date=None):
    if date is None:
        date = datetime.now().date()
    else:
        date = date if isinstance(date, datetime) else datetime.fromisoformat(str(date)).date()
    week_start = date - timedelta(days=date.weekday())
    return week_start.strftime("%Y-%m-%d")


def get_user_usage(user_id):
    conn = _connect()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(_sql("SELECT count FROM usage_logs WHERE user_id = ? AND date = ?"), (user_id, today))
        result = c.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()


def get_ip_week_usage(ip):
    conn = _connect()
    try:
        c = conn.cursor()
        week_start = get_week_start()
        c.execute(_sql("SELECT count FROM ip_usage WHERE ip = ? AND week_start = ?"), (ip, week_start))
        result = c.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()


def increment_ip_usage(ip):
    conn = _connect()
    try:
        c = conn.cursor()
        week_start = get_week_start()
        c.execute(
            _sql("""INSERT INTO ip_usage (ip, week_start, count)
                     VALUES (?, ?, 1)
                     ON CONFLICT (ip, week_start)
                     DO UPDATE SET count = ip_usage.count + 1"""),
            (ip, week_start),
        )
        conn.commit()
    finally:
        conn.close()


def get_device_week_usage(device_key):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            _sql("SELECT count FROM device_week_usage WHERE device_key = ? AND week_start = ?"),
            (device_key, get_week_start()),
        )
        row = c.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_device_access(device_key, free_limit=1):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            _sql("SELECT unlocked_until, allowance, used, source FROM device_unlocks WHERE device_key = ?"),
            (device_key,),
        )
        row = c.fetchone()
        if row:
            unlocked_until = datetime.fromisoformat(str(row[0]))
            if datetime.now() < unlocked_until and int(row[2]) < int(row[1]):
                return {
                    "allowed": True,
                    "mode": "unlocked",
                    "remaining": int(row[1]) - int(row[2]),
                    "unlocked_until": str(row[0]),
                    "source": row[3],
                }
        free_used = get_device_week_usage(device_key)
        return {
            "allowed": free_used < free_limit,
            "mode": "free",
            "remaining": max(0, free_limit - free_used),
            "unlocked_until": None,
            "source": None,
        }
    finally:
        conn.close()


def record_device_activation(device_key, free_limit=1):
    conn = _connect()
    try:
        c = conn.cursor()
        if not USING_POSTGRES:
            c.execute("BEGIN IMMEDIATE")
        select_unlock = """SELECT unlocked_until, allowance, used
                           FROM device_unlocks WHERE device_key = ?"""
        if USING_POSTGRES:
            select_unlock += " FOR UPDATE"
        c.execute(_sql(select_unlock), (device_key,))
        row = c.fetchone()
        if row and datetime.now() < datetime.fromisoformat(str(row[0])) and int(row[2]) < int(row[1]):
            c.execute(
                _sql("UPDATE device_unlocks SET used = used + 1 WHERE device_key = ?"),
                (device_key,),
            )
            conn.commit()
            return "unlocked"

        week_start = get_week_start()
        c.execute(
            _sql("SELECT count FROM device_week_usage WHERE device_key = ? AND week_start = ?"),
            (device_key, week_start),
        )
        used = c.fetchone()
        if used and int(used[0]) >= free_limit:
            conn.rollback()
            return None
        c.execute(
            _sql("""INSERT INTO device_week_usage (device_key, week_start, count)
                     VALUES (?, ?, 1)
                     ON CONFLICT (device_key, week_start)
                     DO UPDATE SET count = device_week_usage.count + 1"""),
            (device_key, week_start),
        )
        conn.commit()
        return "free"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def unlock_device(device_key, days=7, allowance=3, source="payment"):
    conn = _connect()
    try:
        c = conn.cursor()
        unlocked_until = (datetime.now() + timedelta(days=days)).isoformat()
        c.execute(
            _sql("""INSERT INTO device_unlocks
                     (device_key, unlocked_until, allowance, used, source)
                     VALUES (?, ?, ?, 0, ?)
                     ON CONFLICT (device_key) DO UPDATE SET
                         unlocked_until = excluded.unlocked_until,
                         allowance = excluded.allowance,
                         used = 0,
                         source = excluded.source"""),
            (device_key, unlocked_until, allowance, source),
        )
        conn.commit()
    finally:
        conn.close()


def get_or_create_device_referral(device_key):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(_sql("SELECT referral_code FROM device_referrals WHERE device_key = ?"), (device_key,))
        row = c.fetchone()
        if row:
            return row[0]
        referral_code = "REF" + uuid.uuid4().hex[:12].upper()
        c.execute(
            _sql("INSERT INTO device_referrals (referral_code, device_key) VALUES (?, ?)"),
            (referral_code, device_key),
        )
        conn.commit()
        return referral_code
    finally:
        conn.close()


def claim_device_referral(referral_code, referred_device, days=7, allowance=3):
    conn = _connect()
    try:
        c = conn.cursor()
        if not USING_POSTGRES:
            c.execute("BEGIN IMMEDIATE")
        c.execute(
            _sql("SELECT device_key FROM device_referrals WHERE referral_code = ?"),
            (referral_code,),
        )
        row = c.fetchone()
        if not row or row[0] == referred_device:
            conn.rollback()
            return False
        owner_device = row[0]
        c.execute(
            _sql("SELECT 1 FROM device_referral_claims WHERE referral_code = ? AND referred_device = ?"),
            (referral_code, referred_device),
        )
        if c.fetchone():
            conn.rollback()
            return False
        now = datetime.now().isoformat()
        unlocked_until = (datetime.now() + timedelta(days=days)).isoformat()
        c.execute(
            _sql("""INSERT INTO device_referral_claims
                     (referral_code, referred_device, claimed_at) VALUES (?, ?, ?)"""),
            (referral_code, referred_device, now),
        )
        c.execute(
            _sql("""INSERT INTO device_unlocks
                     (device_key, unlocked_until, allowance, used, source)
                     VALUES (?, ?, ?, 0, 'share')
                     ON CONFLICT (device_key) DO UPDATE SET
                         unlocked_until = excluded.unlocked_until,
                         allowance = excluded.allowance,
                         used = 0,
                         source = excluded.source"""),
            (owner_device, unlocked_until, allowance),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_ip_unlock_until(ip):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(_sql("SELECT unlocked_until FROM ip_unlocks WHERE ip = ?"), (ip,))
        result = c.fetchone()
        if not result or not result[0]:
            return None
        try:
            return datetime.fromisoformat(result[0])
        except ValueError:
            return None
    finally:
        conn.close()


def is_ip_unlocked(ip):
    unlocked_until = get_ip_unlock_until(ip)
    return unlocked_until is not None and datetime.now() < unlocked_until


def unlock_ip(ip, days=7):
    conn = _connect()
    try:
        c = conn.cursor()
        unlocked_until = (datetime.now() + timedelta(days=days)).isoformat()
        c.execute(
            _sql("""INSERT INTO ip_unlocks (ip, unlocked_until)
                     VALUES (?, ?)
                     ON CONFLICT (ip)
                     DO UPDATE SET unlocked_until = excluded.unlocked_until"""),
            (ip, unlocked_until),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_payment_by_ip(ip):
    conn = _connect()
    try:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute(_sql("""SELECT order_id, amount, status, created_at, paid_at, expires_at, payment_url
                         FROM payment_orders
                         WHERE ip = ? AND status = 'pending' AND expires_at > ?
                         ORDER BY created_at DESC LIMIT 1"""),
                  (ip, now))
        row = c.fetchone()
        if not row:
            return None
        return {
            "order_id": row[0],
            "amount": row[1],
            "status": row[2],
            "created_at": row[3],
            "paid_at": row[4],
            "expires_at": row[5],
            "payment_url": row[6],
        }
    finally:
        conn.close()


def get_pending_payment_by_device(device_key):
    conn = _connect()
    try:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute(_sql("""SELECT order_id, amount, status, created_at, paid_at, expires_at, payment_url
                         FROM payment_orders
                         WHERE device_key = ? AND status = 'pending' AND expires_at > ?
                         ORDER BY created_at DESC LIMIT 1"""),
                  (device_key, now))
        row = c.fetchone()
        if not row:
            return None
        return {
            "order_id": row[0],
            "amount": row[1],
            "status": row[2],
            "created_at": row[3],
            "paid_at": row[4],
            "expires_at": row[5],
            "payment_url": row[6],
        }
    finally:
        conn.close()


def create_payment_order(ip, amount, payment_url, expires_hours=24, order_id=None, device_key=None):
    conn = _connect()
    try:
        c = conn.cursor()
        if order_id is None:
            order_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(hours=expires_hours)).isoformat()
        c.execute(
            _sql("""INSERT INTO payment_orders
                     (order_id, ip, device_key, amount, status, created_at, paid_at, expires_at, payment_url)
                     VALUES (?, ?, ?, ?, 'pending', ?, NULL, ?, ?)"""),
            (order_id, ip, device_key, amount, now, expires_at, payment_url),
        )
        conn.commit()
        return order_id
    finally:
        conn.close()


def get_payment_order(order_id):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(_sql("""SELECT order_id, ip, device_key, amount, status, created_at, paid_at, expires_at, payment_url
                         FROM payment_orders
                         WHERE order_id = ?"""),
                  (order_id,))
        row = c.fetchone()
        if not row:
            return None
        return {
            "order_id": row[0],
            "ip": row[1],
            "device_key": row[2],
            "amount": row[3],
            "status": row[4],
            "created_at": row[5],
            "paid_at": row[6],
            "expires_at": row[7],
            "payment_url": row[8],
        }
    finally:
        conn.close()


def set_payment_paid(order_id):
    conn = _connect()
    try:
        c = conn.cursor()
        paid_at = datetime.now().isoformat()
        c.execute(
            _sql("""UPDATE payment_orders
                     SET status = 'paid', paid_at = ?
                     WHERE order_id = ?"""),
            (paid_at, order_id),
        )
        conn.commit()
    finally:
        conn.close()


def attach_paid_order_to_device(order_id, device_key, days=7, allowance=3):
    conn = _connect()
    try:
        c = conn.cursor()
        if not USING_POSTGRES:
            c.execute("BEGIN IMMEDIATE")
        c.execute(
            _sql("""UPDATE payment_orders SET device_key = ?
                     WHERE order_id = ? AND status = 'paid' AND device_key IS NULL"""),
            (device_key, order_id),
        )
        c.execute(_sql("SELECT device_key FROM payment_orders WHERE order_id = ?"), (order_id,))
        row = c.fetchone()
        if not row or row[0] != device_key:
            conn.rollback()
            return False
        unlocked_until = (datetime.now() + timedelta(days=days)).isoformat()
        c.execute(
            _sql("""INSERT INTO device_unlocks
                     (device_key, unlocked_until, allowance, used, source)
                     VALUES (?, ?, ?, 0, 'payment')
                     ON CONFLICT (device_key) DO UPDATE SET
                         unlocked_until = excluded.unlocked_until,
                         allowance = excluded.allowance,
                         used = 0,
                         source = excluded.source"""),
            (device_key, unlocked_until, allowance),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def confirm_payment(order_id, transaction_id, received_amount, unlock_days=7, unlock_uses=3):
    """Atomically record a SePay transaction, pay the order and unlock its IP."""
    conn = _connect()
    try:
        c = conn.cursor()
        if not USING_POSTGRES:
            c.execute("BEGIN IMMEDIATE")

        select_order = "SELECT ip, device_key, amount, status, expires_at FROM payment_orders WHERE order_id = ?"
        if USING_POSTGRES:
            select_order += " FOR UPDATE"
        c.execute(_sql(select_order), (order_id,))
        row = c.fetchone()
        if not row:
            conn.rollback()
            return "not_found"

        ip, device_key, expected_amount, status, expires_at = row
        if status == "paid":
            conn.rollback()
            return "already_paid"
        if expires_at and datetime.now() >= datetime.fromisoformat(str(expires_at)):
            conn.rollback()
            return "expired"
        if int(received_amount) != int(expected_amount):
            conn.rollback()
            return "amount_mismatch"

        c.execute(
            _sql("SELECT 1 FROM payment_transactions WHERE transaction_id = ?"),
            (transaction_id,),
        )
        if c.fetchone():
            conn.rollback()
            return "duplicate"

        now = datetime.now().isoformat()
        unlocked_until = (datetime.now() + timedelta(days=unlock_days)).isoformat()
        c.execute(
            _sql("""INSERT INTO payment_transactions
                     (transaction_id, order_id, received_amount, created_at)
                     VALUES (?, ?, ?, ?)"""),
            (transaction_id, order_id, int(received_amount), now),
        )
        c.execute(
            _sql("""UPDATE payment_orders SET status = 'paid', paid_at = ?
                     WHERE order_id = ? AND status = 'pending'"""),
            (now, order_id),
        )
        c.execute(
            _sql("""INSERT INTO ip_unlocks (ip, unlocked_until) VALUES (?, ?)
                     ON CONFLICT (ip) DO UPDATE SET unlocked_until = excluded.unlocked_until"""),
            (ip, unlocked_until),
        )
        if device_key:
            c.execute(
                _sql("""INSERT INTO device_unlocks
                         (device_key, unlocked_until, allowance, used, source)
                         VALUES (?, ?, ?, 0, 'payment')
                         ON CONFLICT (device_key) DO UPDATE SET
                             unlocked_until = excluded.unlocked_until,
                             allowance = excluded.allowance,
                             used = 0,
                             source = excluded.source"""),
                (device_key, unlocked_until, unlock_uses),
            )
        conn.commit()
        return "paid"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def increment_usage(user_id):
    conn = _connect()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(
            _sql("""INSERT INTO usage_logs (user_id, date, count)
                     VALUES (?, ?, 1)
                     ON CONFLICT (user_id, date)
                     DO UPDATE SET count = usage_logs.count + 1"""),
            (user_id, today),
        )
        conn.commit()
    finally:
        conn.close()


def get_referral_bonus(user_id):
    conn = _connect()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(_sql("SELECT count FROM referral_bonus_logs WHERE user_id = ? AND date = ?"), (user_id, today))
        result = c.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()


def grant_referral_bonus(user_id, amount=1):
    conn = _connect()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(
            _sql("""INSERT INTO referral_bonus_logs (user_id, date, count)
                     VALUES (?, ?, ?)
                     ON CONFLICT (user_id, date)
                     DO UPDATE SET count = referral_bonus_logs.count + excluded.count"""),
            (user_id, today, amount),
        )
        conn.commit()
    finally:
        conn.close()


def check_can_request(user_id, max_limit=2):
    return get_user_usage(user_id) < max_limit + get_referral_bonus(user_id)


def set_lang(user_id, lang):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            _sql("""INSERT INTO user_settings (user_id, language) VALUES (?, ?)
                     ON CONFLICT (user_id) DO UPDATE SET language = excluded.language"""),
            (user_id, lang),
        )
        conn.commit()
    finally:
        conn.close()


def get_lang(user_id):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(_sql("SELECT language FROM user_settings WHERE user_id = ?"), (user_id,))
        result = c.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


def get_all_users():
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM usage_logs UNION SELECT user_id FROM user_settings")
        return [row[0] for row in c.fetchall()]
    finally:
        conn.close()


def reset_usage(user_id):
    conn = _connect()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(_sql("DELETE FROM usage_logs WHERE user_id = ? AND date = ?"), (user_id, today))
        conn.commit()
    finally:
        conn.close()


def set_config(key, value):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            _sql("""INSERT INTO bot_config (key, value) VALUES (?, ?)
                     ON CONFLICT (key) DO UPDATE SET value = excluded.value"""),
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_config(key, default=None):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(_sql("SELECT value FROM bot_config WHERE key = ?"), (key,))
        result = c.fetchone()
        return result[0] if result else default
    finally:
        conn.close()


def log_request(user_id, uid, status):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            _sql("INSERT INTO request_logs (user_id, uid, status) VALUES (?, ?, ?)"),
            (user_id, uid, status),
        )
        conn.commit()
    finally:
        conn.close()


def get_successful_uids():
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT uid FROM request_logs WHERE status = 'SUCCESS' AND uid IS NOT NULL")
        return [row[0] for row in c.fetchall() if row[0]]
    finally:
        conn.close()


def get_stats():
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM request_logs")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM request_logs WHERE status = 'SUCCESS'")
        success = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM request_logs WHERE status != 'SUCCESS'")
        fail = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT user_id) FROM request_logs")
        unique_users = c.fetchone()[0]
        return {
            "total": total,
            "success": success,
            "fail": fail,
            "unique_users": unique_users,
        }
    finally:
        conn.close()


init_db()
