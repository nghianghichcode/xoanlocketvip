import asyncio
import threading
import logging
import os
import http.server
import socketserver
import json
from urllib.parse import urlparse
from functools import partial
from app import database as db
from app.services import locket, nextdns
from app.config import TOKEN_SETS, NEXTDNS_KEY, NEXTDNS_INSTALL_URL
from app.bot import run_bot

logger = logging.getLogger(__name__)

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
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

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
                if not uid:
                    self._send_json(400, {"success": False, "message": "Thiếu thông tin UID."})
                    return
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Inject Gold using the first available token
                token_config = TOKEN_SETS[0]
                success, msg = loop.run_until_complete(locket.inject_gold(uid, token_config))
                
                if success:
                    referrer_id = data.get('referrer_id')
                    if referrer_id:
                        try:
                            referrer_id = int(referrer_id)
                        except (TypeError, ValueError):
                            referrer_id = None
                        if referrer_id and referrer_id != uid:
                            db.grant_referral_bonus(referrer_id)

                    _, dns_url = loop.run_until_complete(
                        nextdns.create_profile(NEXTDNS_KEY, None, install_url=NEXTDNS_INSTALL_URL)
                    )
                    final_dns_url = dns_url or NEXTDNS_INSTALL_URL

                    self._send_json(200, {"success": True, "uid": uid, "dns_url": final_dns_url})
                else:
                    self._send_json(400, {"success": False, "message": msg})
                    
            except Exception as e:
                logger.error(f"Web API Error activate: {e}")
                self._send_json(500, {"success": False, "message": "Lỗi máy chủ nội bộ."})
        else:
            self.send_error(404, "Not Found")

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
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

if __name__ == "__main__":
    # Đẩy web server sang 1 luồng riêng biệt (Render yêu cầu bind PORT)
    threading.Thread(target=start_web_server, daemon=True).start()

    # Đẩy daemon sang 1 luồng riêng biệt
    threading.Thread(target=start_daemon, daemon=True).start()
    
    # Chạy bot Telegram ở luồng chính
    run_bot()
