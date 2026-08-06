import re
import secrets
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import requests


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
    for field in ("code", "content", "transaction_content", "description"):
        value = str(payload.get(field) or "").upper()
        match = re.search(pattern, value)
        if match:
            return match.group(0)
    return None


def match_sepay_transaction(transactions, order_id, amount, account_no):
    expected_order = order_id.upper()
    expected_account = str(account_no).strip()
    expected_amount = Decimal(str(amount))
    for transaction in transactions:
        candidate_order = extract_order_id(transaction, expected_order[:-12])
        if candidate_order != expected_order:
            continue
        candidate_account = str(
            transaction.get("account_number") or transaction.get("accountNumber") or ""
        ).strip()
        if candidate_account and candidate_account != expected_account:
            continue
        raw_amount = transaction.get("amount_in", transaction.get("transferAmount"))
        try:
            if Decimal(str(raw_amount)) != expected_amount:
                continue
        except (InvalidOperation, TypeError):
            continue
        return transaction
    return None


def find_sepay_transaction(api_url, api_token, account_no, amount, order_id, timeout=15):
    if not api_token:
        return None
    response = requests.get(
        api_url,
        params={
            "account_number": account_no,
            "amount_in": int(amount),
            "limit": 50,
        },
        headers={"Authorization": f"Bearer {api_token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    transactions = payload.get("transactions") or payload.get("data") or []
    if isinstance(transactions, dict):
        transactions = transactions.get("transactions") or []
    return match_sepay_transaction(transactions, order_id, amount, account_no)
