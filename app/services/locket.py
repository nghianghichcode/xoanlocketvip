import aiohttp
import json
import re
import time
import asyncio
from app.config import TOKEN_SETS

# Headers chuẩn lấy từ traffic dump (Locket v5.43.0 / iOS 17.4.1)
HEADERS = {
    'User-Agent':               'Locket/1 CFNetwork/1494.0.7 Darwin/23.4.0',
    'Content-Type':             'application/json',
    'Authorization':            'Bearer appl_JngFETzdodyLmCREOlwTUtXdQik',
    'X-Platform':               'iOS',
    'X-Platform-Version':       'Version 17.4.1 (Build 21E236)',
    'X-Platform-Device':        'iPhone15,2',
    'X-Platform-Flavor':        'native',
    'X-Version':                '5.43.0',
    'X-Client-Version':         '2.51.0',
    'X-Client-Bundle-ID':       'com.locket.Locket',
    'X-Client-Build-Version':   '1',
    'X-StoreKit2-Enabled':      'true',
    'X-StoreKit-Version':       '2',
    'X-Observer-Mode-Enabled':  'false',
    'X-Is-Sandbox':             'false',   # bị ghi đè theo token_config
    'X-Storefront':             'VNM',
    'X-Apple-Device-Identifier':'0EFEE35B-8938-4BFE-B5B8-EA014BCD65B0',
    'X-Preferred-Locales':      'vi_VN',
    'X-Nonce':                  'Kz1Sp5GLDmEKK1Cj',
    'X-RevenueCat-ETag':        'a117da251e83b91a',
    'X-Is-Backgrounded':        'false',
    'X-Retry-Count':            '0',
    'X-Is-Debug-Build':         'false',
    'Accept-Language':          'vi-VN,vi;q=0.9',
    'Sentry-Trace':             'c5d3f77e4a6340c3ba31a0109b2b991d-bc7efdce0be7466d-0',
    'Baggage':                  'sentry-environment=production,sentry-public_key=78fa64317f434fd89d9cc728dd168f50,sentry-release=com.locket.Locket%402.51.0%2B1,sentry-trace_id=c5d3f77e4a6340c3ba31a0109b2b991d',
}

class Clr:
    HEADER  = '\033[95m'
    BLUE    = '\033[94m'
    GREEN   = '\033[92m'
    WARNING = '\033[93m'
    FAIL    = '\033[91m'
    ENDC    = '\033[0m'
    BOLD    = '\033[1m'

async def resolve_uid(username):
    url = f"https://locket.cam/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "Accept": "text/html"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, allow_redirects=True, timeout=10) as res:
                html = await res.text()
                redirect_url = str(res.url)

                def extract(text):
                    if not text: return None
                    m = re.search(r'/invites/([A-Za-z0-9]{28})', text)
                    if m: return m.group(1)
                    lp = re.search(r'link=([^\s"\'>]+)', text)
                    if lp:
                        try:
                            d = lp.group(1).replace('%3A', ':').replace('%2F', '/')
                            dm = re.search(r'/invites/([A-Za-z0-9]{28})', d)
                            if dm: return dm.group(1)
                        except:
                            pass
                    return None

                return extract(redirect_url) or extract(html)
    except Exception:
        return None

async def check_status(uid):
    url = f"https://api.revenuecat.com/v1/subscribers/{uid}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=10) as res:
                if 200 <= res.status < 300:
                    data = await res.json()
                    entitlements = data.get('subscriber', {}).get('entitlements', {}).get('Gold', {})
                    if entitlements:
                        expires_date = entitlements.get('expires_date')
                        return {"active": True, "expires": expires_date}
                    return {"active": False}
                return {"active": False}
    except Exception:
        return None

async def inject_gold(uid, token_config, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)

    url = "https://api.revenuecat.com/v1/receipts"

    fetch_token     = token_config['fetch_token']
    app_transaction = token_config['app_transaction']
    is_sandbox      = token_config['is_sandbox']

    now_ms = int(time.time() * 1000)

    body = {
        "observer_mode":         False,
        "initiation_source":     "restore",
        "subscription_group_id": "21419447",
        "app_user_id":           uid,
        "attributes": {
            "$firebaseAppInstanceId": {
                "updated_at_ms": now_ms,
                "value": "2D00DBC0255C46229FD693B296393B9A"
            },
            "$attConsentStatus": {
                "updated_at_ms": now_ms,
                "value": "authorized"
            },
            "$amplitudeDeviceId": {
                "value": "0EFEE35B-8938-4BFE-B5B8-EA014BCD65B0",
                "updated_at_ms": now_ms
            },
            "$amplitudeUserId": {
                "updated_at_ms": now_ms,
                "value": uid
            }
        },
        "normal_duration":  "P1M",
        "currency":         "VND",
        "is_restore":       True,
        "app_transaction":  app_transaction,
        "fetch_token":      fetch_token,
        "product_id":       "locket_199_1m",
        "store_country":    "VNM",
        "price":            "49000",
        "offers":           [],
    }

    current_headers = HEADERS.copy()
    current_headers['X-Is-Sandbox'] = str(is_sandbox).lower()

    if token_config.get('hash_params'):
        current_headers['X-Post-Params-Hash'] = token_config['hash_params']
    if token_config.get('hash_headers'):
        current_headers['X-Headers-Hash'] = token_config['hash_headers']

    log(f"{Clr.BLUE}[*] Target Identified:{Clr.ENDC} {uid}")
    log(f"{Clr.BLUE}[*] Loading Exploit Payload (RevenueCat)...{Clr.ENDC}")
    log(f"{Clr.BLUE}[*] Using Token Set: {token_config.get('name', 'Custom')}{Clr.ENDC}")

    async with aiohttp.ClientSession() as session:
        for attempt in range(5):
            try:
                log(f"{Clr.WARNING}[>] Attempt {attempt+1}/5:{Clr.ENDC} Sending Receipt...")
                async with session.post(url, headers=current_headers, json=body, timeout=15) as res:
                    status_code = res.status

                    if status_code == 200:
                        log(f"{Clr.GREEN}[+] HTTP 200 OK.{Clr.ENDC} Verifying Entitlement...")
                        status = await check_status(uid)
                        if status and status.get('active'):
                            log(f"{Clr.GREEN}[SUCCESS] Gold Entitlement Active!{Clr.ENDC}")
                            return True, "SUCCESS"
                        else:
                            log(f"{Clr.WARNING}[!] Entitlement not found immediately. Retrying verification...{Clr.ENDC}")
                            await asyncio.sleep(2)
                            status = await check_status(uid)
                            if status and status.get('active'):
                                log(f"{Clr.GREEN}[SUCCESS] Gold Active after delay.{Clr.ENDC}")
                                return True, "SUCCESS"
                            log(f"{Clr.FAIL}[-] Exploitation Failed: Valid receipt but no Gold.{Clr.ENDC}")
                            return False, "Accepted but NO Gold (Expired?)"

                    elif status_code == 529:
                        log(f"{Clr.WARNING}[!] Server Busy (529). Cooldown 2s...{Clr.ENDC}")
                        await asyncio.sleep(2)
                        continue

                    else:
                        msg = "Unknown Error"
                        try:
                            resp_json = await res.json()
                            msg = resp_json.get('message', str(status_code))
                        except:
                            msg = str(status_code)
                        log(f"{Clr.FAIL}[x] Request Rejected: {msg}{Clr.ENDC}")
                        return False, f"Rejected: {msg}"

            except Exception as e:
                log(f"{Clr.FAIL}[!] Network Error: {e}{Clr.ENDC}")
                if attempt == 4:
                    return False, f"Request Error: {str(e)}"
                await asyncio.sleep(2)

    return False, "Timeout / Failed after retries"
