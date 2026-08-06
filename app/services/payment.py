import re
import secrets
import unicodedata
from urllib.parse import urlencode


def normalize_order_prefix(prefix):
    value = re.sub(r"[^A-Z0-9]", "", (prefix or "XOAN").upper())
    return value[:8] or "XOAN"


def generate_order_id(prefix="XOAN"):
    """Create a transfer-description-safe payment code."""
    return f"{normalize_order_prefix(prefix)}{secrets.token_hex(6).upper()}"


def build_vietqr_url(base_url, account_no, bank_code, amount, order_id, account_name=""):
    if not account_no or not bank_code:
        raise ValueError("Missing VIETQR_ACCOUNT_NO or VIETQR_BANK_CODE/VIETQR_BANK_BIN")

    params = {
        "acc": account_no,
        "bank": bank_code,
        "amount": int(amount),
        "des": order_id,
        "template": "compact",
        "showinfo": "true",
        "fullacc": "true",
    }
    if account_name:
        ascii_name = unicodedata.normalize("NFKD", account_name.replace("Đ", "D").replace("đ", "d"))
        ascii_name = ascii_name.encode("ascii", "ignore").decode("ascii").upper()
        params["holder"] = re.sub(r"[^A-Z0-9 ]", "", ascii_name)[:80]
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(params)}"


def extract_order_id(payload, prefix="XOAN"):
    normalized_prefix = normalize_order_prefix(prefix)
    pattern = rf"{re.escape(normalized_prefix)}[A-F0-9]{{12}}"
    for field in ("code", "content", "description"):
        value = str(payload.get(field) or "").upper()
        match = re.search(pattern, value)
        if match:
            return match.group(0)
    return None
