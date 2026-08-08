import asyncio
import threading
import logging
import os
import http.server
import socketserver
import json
import secrets
import time
import re
import sys
from urllib.parse import urlparse, parse_qs
from app import database as db
from app.services import locket, nextdns, payment
from app.config import (
    TOKEN_SETS,
    NEXTDNS_KEY,
    NEXTDNS_INSTALL_URL,
    WEEKLY_USAGE_LIMIT,
    PAYMENT_UNLOCK_AMOUNT,
    PAYMENT_UNLOCK_DAYS,
    PAYMENT_UNLOCK_USES,
    SHARE_UNLOCK_USES,
    SEPAY_WEBHOOK_SECRET,
    SEPAY_API_TOKEN,
    SEPAY_API_URL,
    VIETQR_BANK_CODE,
    VIETQR_ACCOUNT_NO,
    VIETQR_ACCOUNT_NAME,
    VIETQR_URL_TEMPLATE,
    PAYMENT_ORDER_PREFIX,
    VIETQR_BANK_NAME,
    SUPPORT_FACEBOOK_URL,
    SUPPORT_TELEGRAM_URL,
    DONATE_TRANSFER_CONTENT,
)
from app.bot import run_bot

logger = logging.getLogger(__name__)
payment_reconcile_lock = threading.Lock()
payment_reconcile_checked_at = {}
payment_reconcile_next_api_call = 0.0


def acquire_reconcile_slot(key):
    global payment_reconcile_next_api_call
    now = time.monotonic()
    with payment_reconcile_lock:
        last_checked = payment_reconcile_checked_at.get(key, 0)
        if now - last_checked < 5 or now < payment_reconcile_next_api_call:
            return False
        payment_reconcile_checked_at[key] = now
        payment_reconcile_next_api_call = now + 0.4
        return True


def reconcile_pending_payment(order):
    """Use SePay's transaction API when a webhook was delayed or misconfigured."""
    if not SEPAY_API_TOKEN or order['status'] != 'pending':
        return False

    if not acquire_reconcile_slot(order['order_id']):
        return False

    try:
        transaction = payment.find_sepay_transaction(
            SEPAY_API_URL,
            SEPAY_API_TOKEN,
            VIETQR_ACCOUNT_NO,
            order['amount'],
            order['order_id'],
        )
        if not transaction:
            return False
        transaction_id = str(
            transaction.get('id') or transaction.get('reference_number') or ''
        ).strip()
        if not transaction_id:
            return False
        result = db.confirm_payment(
            order['order_id'], transaction_id, order['amount'], PAYMENT_UNLOCK_DAYS,
            PAYMENT_UNLOCK_USES,
        )
        logger.info("SePay reconciliation for order %s: %s", order['order_id'], result)
        return result in ('paid', 'already_paid')
    except Exception as exc:
        logger.warning("SePay reconciliation failed for order %s: %s", order['order_id'], exc)
        return False


def recover_paid_order(order_id, client_ip, device_key):
    """Recover a paid order after an ephemeral Railway filesystem restart."""
    if not SEPAY_API_TOKEN:
        return None
    if payment.extract_order_id({'code': order_id}, PAYMENT_ORDER_PREFIX) != order_id:
        return None
    if not acquire_reconcile_slot(f"recover:{order_id}"):
        return None
    try:
        transaction = payment.find_sepay_transaction(
            SEPAY_API_URL,
            SEPAY_API_TOKEN,
            VIETQR_ACCOUNT_NO,
            PAYMENT_UNLOCK_AMOUNT,
            order_id,
        )
        if not transaction:
            return None
        payment_url = payment.build_vietqr_url(
            VIETQR_URL_TEMPLATE,
            VIETQR_ACCOUNT_NO,
            VIETQR_BANK_CODE,
            PAYMENT_UNLOCK_AMOUNT,
            order_id,
            VIETQR_ACCOUNT_NAME,
        )
        try:
            db.create_payment_order(
                client_ip,
                PAYMENT_UNLOCK_AMOUNT,
                payment_url,
                order_id=order_id,
                device_key=device_key,
            )
        except Exception:
            existing = db.get_payment_order(order_id)
            if not existing or (
                existing.get('device_key') and existing['device_key'] != device_key
            ):
                return None
        transaction_id = str(
            transaction.get('id') or transaction.get('reference_number') or ''
        ).strip()
        if not transaction_id:
            return None
        db.confirm_payment(
            order_id, transaction_id, PAYMENT_UNLOCK_AMOUNT,
            PAYMENT_UNLOCK_DAYS, PAYMENT_UNLOCK_USES,
        )
        logger.info("Recovered paid SePay order %s after database restart", order_id)
        return db.get_payment_order(order_id)
    except Exception as exc:
        logger.warning("Unable to recover SePay order %s: %s", order_id, exc)
        return None

async def inject_worker(uid, token_config):
    """Worker bơm lẻ cho 1 uid, retry tối đa 3 lần nếu server bận"""
    for _ in range(3):
        success, _ = await locket.inject_gold(uid, token_config, log_callback=None)
        if success:
            return True
        await asyncio.sleep(1)
    return False

async def auto_renew_daemon():
    print("[\033[94m*\033[0m] Mass-Injector Daemon Khởi Động. Sẵn sàng gánh 200+ mạng.")
    
    while True:
        try:
            uids = db.get_successful_uids()

            total_users = len(uids)
            if total_users == 0:
                await asyncio.sleep(3600)
                continue
                
            print(f"[\033[93m>\033[0m] Bắt đầu rải thảm {total_users} users...")
            
            BATCH_SIZE = 10
            success_count = 0
            
            for i in range(0, total_users, BATCH_SIZE):
                batch_uids = uids[i:i+BATCH_SIZE]
                tasks = []
                
                for j, uid in enumerate(batch_uids):
                    token_idx = (i + j) % len(TOKEN_SETS) 
                    token_config = TOKEN_SETS[token_idx]
                    tasks.append(inject_worker(uid, token_config))
                
                results = await asyncio.gather(*tasks)
                success_count += sum(results)
                
                await asyncio.sleep(2)
                
            print(f"[\033[92m+\033[0m] Càn quét hoàn tất: {success_count}/{total_users} active.")
            
            # 3 tiếng quật 1 lần. Mày thích nhanh hơn thì sửa số 3 thành 2 hoặc 1.
            await asyncio.sleep(3 * 3600)
            
        except Exception as e:
            logger.error(f"Lỗi Daemon: {e}")
            await asyncio.sleep(60)

def start_daemon():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(auto_renew_daemon())


def normalize_username_input(username):
    username = (username or '').strip()
    if not username:
        return ''

    # Support full Locket links like https://locket.cam/username?ref=...
    if username.startswith('http://') or username.startswith('https://'):
        try:
            parsed = urlparse(username)
            username = parsed.path.lstrip('/')
        except Exception:
            pass

    # Support raw links without scheme
    if 'locket.cam/' in username:
        username = username.split('locket.cam/')[-1]

    username = username.split('?')[0].split('#')[0].rstrip('/')
    return username

class WebAPIHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve from the 'website' directory without changing the global cwd
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'website')
        super().__init__(*args, directory=web_dir, **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _client_ip(self):
        forwarded = self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return self.client_address[0]

    @staticmethod
    def _valid_device_key(value):
        value = str(value or '').strip().lower()
        return value if re.fullmatch(r"[a-f0-9]{64}", value) else None

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/support-config':
            try:
                donate_qr_url = payment.build_donate_vietqr_url(
                    VIETQR_URL_TEMPLATE,
                    VIETQR_ACCOUNT_NO,
                    VIETQR_BANK_CODE,
                    DONATE_TRANSFER_CONTENT,
                    VIETQR_ACCOUNT_NAME,
                )
            except ValueError:
                donate_qr_url = ""

            self._send_json(200, {
                "success": True,
                "facebook_url": SUPPORT_FACEBOOK_URL,
                "telegram_url": SUPPORT_TELEGRAM_URL,
                "donate_qr_url": donate_qr_url,
                "bank_name": VIETQR_BANK_NAME,
                "account_name": VIETQR_ACCOUNT_NAME,
                "transfer_content": DONATE_TRANSFER_CONTENT,
            })
            return

        if parsed_path.path != '/api/payment-status':
            return super().do_GET()

        order_id = parse_qs(parsed_path.query).get('order_id', [''])[0].strip().upper()
        device_key = self._valid_device_key(
            parse_qs(parsed_path.query).get('device_id', [''])[0]
        )
        if not device_key:
            self._send_json(400, {"success": False, "message": "Thiếu mã nhận diện thiết bị."})
            return
        order = db.get_payment_order(order_id) if order_id else None
        if not order and order_id:
            order = recover_paid_order(order_id, self._client_ip(), device_key)
        belongs_to_device = order and (
            order.get('device_key') == device_key
            or (not order.get('device_key') and order['ip'] == self._client_ip())
        )
        if not belongs_to_device:
            self._send_json(404, {"success": False, "message": "Khong tim thay don thanh toan."})
            return
        if order['status'] == 'pending' and reconcile_pending_payment(order):
            order = db.get_payment_order(order_id)
        if order['status'] == 'paid' and not order.get('device_key'):
            if db.attach_paid_order_to_device(
                order_id, device_key, PAYMENT_UNLOCK_DAYS, PAYMENT_UNLOCK_USES
            ):
                order = db.get_payment_order(order_id)
        device_access = db.get_device_access(device_key, WEEKLY_USAGE_LIMIT)
        unlocked = order['status'] == 'paid' or device_access['mode'] == 'unlocked'
        self._send_json(200, {
            "success": True,
            "order_id": order_id,
            "status": order['status'],
            "paid": order['status'] == 'paid',
            "unlocked": unlocked,
            "remaining_uses": device_access['remaining'],
            "message": (
                f"Đã mở khóa {device_access['remaining']} lượt sử dụng trong 7 ngày."
                if unlocked
                else "Đang chờ SePay xác nhận giao dịch."
            ),
        })

    def do_POST(self):
        parsed_path = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        
        if parsed_path.path == '/api/check_user':
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                username = normalize_username_input(data.get('username', ''))
                if not username:
                    self._send_json(400, {"success": False, "message": "Vui lòng nhập Username."})
                    return
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                uid = loop.run_until_complete(locket.resolve_uid(username))
                if not uid:
                    self._send_json(400, {"success": False, "message": "Không tìm thấy tài khoản hoặc link sai!"})
                    return
                
                status = loop.run_until_complete(locket.check_status(uid))
                has_gold = status and status.get('active', False)
                
                self._send_json(200, {"success": True, "uid": uid, "username": username, "has_gold": has_gold})
                    
            except Exception as e:
                logger.error(f"Web API Error check_user: {e}")
                self._send_json(500, {"success": False, "message": "Lỗi máy chủ nội bộ."})

        elif parsed_path.path == '/api/activate':
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                uid = data.get('uid', '').strip()
                device_key = self._valid_device_key(data.get('device_id'))
                if not uid:
                    self._send_json(400, {"success": False, "message": "Thiếu thông tin UID."})
                    return
                if not device_key:
                    self._send_json(400, {"success": False, "message": "Không nhận diện được thiết bị."})
                    return

                client_ip = self._client_ip()
                if not client_ip:
                    self._send_json(400, {"success": False, "message": "Không xác định được IP người dùng."})
                    return

                access = db.get_device_access(device_key, WEEKLY_USAGE_LIMIT)
                if not access['allowed']:
                    pending_payment = db.get_pending_payment_by_device(device_key)
                    referral_code = db.get_or_create_device_referral(device_key)
                    valid_pending = (
                        pending_payment
                        and pending_payment['order_id'].upper().startswith(
                            payment.normalize_order_prefix(PAYMENT_ORDER_PREFIX)
                        )
                        and 'sepay.example.com' not in (pending_payment['payment_url'] or '')
                    )
                    if valid_pending:
                        self._send_json(403, {
                            "success": False,
                            "message": "Đã dùng lượt miễn phí. Chia sẻ nhận 1 lượt hoặc thanh toán nhận 3 lượt/7 ngày.",
                            "payment_url": pending_payment['payment_url'],
                            "payment_qr_url": pending_payment['payment_url'],
                            "order_id": pending_payment['order_id'],
                            "amount": pending_payment['amount'],
                            "account_no": VIETQR_ACCOUNT_NO,
                            "account_name": VIETQR_ACCOUNT_NAME,
                            "bank_code": VIETQR_BANK_CODE,
                            "referral_code": referral_code,
                            "unlock_uses": PAYMENT_UNLOCK_USES,
                            "share_unlock_uses": SHARE_UNLOCK_USES,
                        })
                    else:
                        order_id = payment.generate_order_id(PAYMENT_ORDER_PREFIX)
                        try:
                            payment_url = payment.build_vietqr_url(
                                VIETQR_URL_TEMPLATE,
                                VIETQR_ACCOUNT_NO,
                                VIETQR_BANK_CODE,
                                PAYMENT_UNLOCK_AMOUNT,
                                order_id,
                                VIETQR_ACCOUNT_NAME,
                            )
                        except ValueError as exc:
                            logger.error("Payment configuration error: %s", exc)
                            self._send_json(500, {
                                "success": False,
                                "message": "Chưa cấu hình VIETQR_ACCOUNT_NO và VIETQR_BANK_CODE/VIETQR_BANK_BIN.",
                            })
                            return

                        db.create_payment_order(
                            client_ip,
                            PAYMENT_UNLOCK_AMOUNT,
                            payment_url,
                            order_id=order_id,
                            device_key=device_key,
                        )
                        self._send_json(403, {
                            "success": False,
                            "message": "Đã dùng lượt miễn phí. Chia sẻ nhận 1 lượt hoặc quét QR nhận 3 lượt/7 ngày.",
                            "payment_url": payment_url,
                            "payment_qr_url": payment_url,
                            "order_id": order_id,
                            "amount": PAYMENT_UNLOCK_AMOUNT,
                            "account_no": VIETQR_ACCOUNT_NO,
                            "account_name": VIETQR_ACCOUNT_NAME,
                            "bank_code": VIETQR_BANK_CODE,
                            "referral_code": referral_code,
                            "unlock_uses": PAYMENT_UNLOCK_USES,
                            "share_unlock_uses": SHARE_UNLOCK_USES,
                        })
                    return

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Inject Gold using the first available token
                token_config = TOKEN_SETS[0]
                success, msg = loop.run_until_complete(locket.inject_gold(uid, token_config))
                
                if success:
                    usage_mode = db.record_device_activation(device_key, WEEKLY_USAGE_LIMIT)
                    referrer_code = str(data.get('referrer_code') or '').strip().upper()
                    if referrer_code:
                        db.claim_device_referral(
                            referrer_code,
                            device_key,
                            PAYMENT_UNLOCK_DAYS,
                            SHARE_UNLOCK_USES,
                        )

                    _, dns_url = loop.run_until_complete(
                        nextdns.create_profile(NEXTDNS_KEY, None, install_url=NEXTDNS_INSTALL_URL)
                    )
                    final_dns_url = dns_url or NEXTDNS_INSTALL_URL

                    remaining = db.get_device_access(device_key, WEEKLY_USAGE_LIMIT)
                    self._send_json(200, {
                        "success": True,
                        "uid": uid,
                        "dns_url": final_dns_url,
                        "usage_mode": usage_mode,
                        "remaining_uses": remaining['remaining'],
                    })
                else:
                    self._send_json(400, {"success": False, "message": msg})
                    
            except Exception as e:
                logger.error(f"Web API Error activate: {e}")
                self._send_json(500, {"success": False, "message": "Lỗi máy chủ nội bộ."})
        elif parsed_path.path in ('/api/sepay/webhook', '/api/payment-confirm'):
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                if not SEPAY_WEBHOOK_SECRET:
                    self._send_json(503, {"success": False, "message": "Webhook API key is not configured."})
                    return

                authorization = self.headers.get('Authorization', '')
                expected_auth = f"Apikey {SEPAY_WEBHOOK_SECRET}"
                if not secrets.compare_digest(authorization, expected_auth):
                    self._send_json(401, {"success": False, "message": "Invalid webhook API key."})
                    return

                if str(data.get('transferType', '')).lower() != 'in':
                    self._send_json(200, {"success": True, "processed": False, "reason": "not_incoming"})
                    return

                webhook_account = str(data.get('accountNumber') or '').strip()
                if webhook_account and webhook_account != VIETQR_ACCOUNT_NO:
                    self._send_json(200, {"success": True, "processed": False, "reason": "wrong_account"})
                    return

                order_id = payment.extract_order_id(data, PAYMENT_ORDER_PREFIX)
                transaction_id = str(data.get('id') or data.get('referenceCode') or '').strip()
                received_amount = data.get('transferAmount')
                if not order_id or not transaction_id or received_amount is None:
                    self._send_json(200, {"success": True, "processed": False, "reason": "no_matching_order"})
                    return

                result = db.confirm_payment(
                    order_id,
                    transaction_id,
                    received_amount,
                    PAYMENT_UNLOCK_DAYS,
                    PAYMENT_UNLOCK_USES,
                )
                self._send_json(200, {
                    "success": True,
                    "processed": result in ('paid', 'already_paid'),
                    "order_id": order_id,
                    "status": result,
                })
            except Exception as e:
                logger.error(f"Web API Error payment-confirm: {e}")
                self._send_json(500, {"success": False, "message": "Lỗi máy chủ nội bộ."})
        else:
            self.send_error(404, "Not Found")

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    
    # Use ThreadingTCPServer so that API requests don't block each other
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", port), WebAPIHandler) as httpd:
        print(f"[\033[92m+\033[0m] Web server (xoan.locket) running on port {port}")
        httpd.serve_forever()

def env_flag(name, default=True):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def configure_console_encoding():
    """Prevent Vietnamese log messages from crashing Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    configure_console_encoding()

    # Đẩy web server sang 1 luồng riêng biệt (Render yêu cầu bind PORT)
    threading.Thread(target=start_web_server, daemon=True).start()

    if env_flag("RUN_RENEW_DAEMON", True):
        threading.Thread(target=start_daemon, daemon=True).start()
    else:
        print("[i] Mass-Injector daemon is disabled.")

    if env_flag("RUN_BOT", True):
        try:
            run_bot()
        except Exception as exc:
            logger.exception("Telegram bot failed to start: %s", exc)
            print("[!] Telegram bot could not start; the website is still running.")
    else:
        print("[i] Telegram bot is disabled. Running website only.")

    # Keep the main process alive when running in web-only mode or after a bot error.
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[i] Server stopped.")
