from urllib.parse import parse_qs, urlparse

from app.services.payment import (
    build_donate_vietqr_url,
    build_vietqr_url,
    extract_order_id,
    generate_order_id,
    match_sepay_transaction,
)


def test_order_id_is_bank_safe_and_unique():
    first = generate_order_id("xoan")
    second = generate_order_id("xoan")
    assert first.startswith("XOAN")
    assert len(first) == 16
    assert first.isalnum()
    assert first != second


def test_vietqr_contains_amount_and_order_code():
    url = build_vietqr_url(
        "https://vietqr.app/img",
        "0123456789",
        "970436",
        20000,
        "XOAN0123456789AB",
        "NGUYEN VAN A",
    )
    params = parse_qs(urlparse(url).query)
    assert params["acc"] == ["0123456789"]
    assert params["amount"] == ["20000"]
    assert params["des"] == ["XOAN0123456789AB"]


def test_donate_vietqr_allows_custom_amount():
    url = build_donate_vietqr_url(
        "https://vietqr.app/img",
        "0123456789",
        "970436",
        "UNG HO XOAN",
        "NGUYEN VAN A",
    )
    params = parse_qs(urlparse(url).query)
    assert params["acc"] == ["0123456789"]
    assert params["des"] == ["UNG HO XOAN"]
    assert "amount" not in params


def test_extract_order_from_official_sepay_fields():
    payload = {
        "code": None,
        "content": "XOAN0123456789AB chuyen tien",
        "description": "incoming transfer",
    }
    assert extract_order_id(payload, "XOAN") == "XOAN0123456789AB"


def test_match_transaction_api_payload():
    transactions = [{
        "id": "123",
        "account_number": "0123456789",
        "amount_in": "20000.00",
        "transaction_content": "XOAN0123456789AB chuyen tien",
    }]
    match = match_sepay_transaction(
        transactions, "XOAN0123456789AB", 20000, "0123456789"
    )
    assert match["id"] == "123"


def test_database_confirms_only_exact_amount_once(tmp_path):
    from app import database as db

    old_name = db.DB_NAME
    old_postgres = db.USING_POSTGRES
    try:
        db.DB_NAME = str(tmp_path / "payments.db")
        db.USING_POSTGRES = False
        db.init_db()
        order_id = "XOAN0123456789AB"
        db.create_payment_order("203.0.113.10", 20000, "https://vietqr.app/img", order_id=order_id)

        assert db.confirm_payment(order_id, "TX-WRONG", 19000, 7) == "amount_mismatch"
        assert db.confirm_payment(order_id, "TX-OK", 20000, 7) == "paid"
        assert db.confirm_payment(order_id, "TX-OK", 20000, 7) == "already_paid"
        assert db.get_payment_order(order_id)["status"] == "paid"
        assert db.is_ip_unlocked("203.0.113.10")
    finally:
        db.DB_NAME = old_name
        db.USING_POSTGRES = old_postgres


def test_device_free_then_three_unlocked_uses(tmp_path):
    from app import database as db

    old_name = db.DB_NAME
    old_postgres = db.USING_POSTGRES
    device = "a" * 64
    try:
        db.DB_NAME = str(tmp_path / "device-limits.db")
        db.USING_POSTGRES = False
        db.init_db()

        assert db.get_device_access(device, 1)["remaining"] == 1
        assert db.record_device_activation(device, 1) == "free"
        assert not db.get_device_access(device, 1)["allowed"]

        db.unlock_device(device, days=7, allowance=3, source="payment")
        assert db.get_device_access(device, 1)["remaining"] == 3
        assert [db.record_device_activation(device, 1) for _ in range(3)] == [
            "unlocked", "unlocked", "unlocked"
        ]
        assert not db.get_device_access(device, 1)["allowed"]
    finally:
        db.DB_NAME = old_name
        db.USING_POSTGRES = old_postgres


def test_payment_and_referral_unlock_devices(tmp_path):
    from app import database as db

    old_name = db.DB_NAME
    old_postgres = db.USING_POSTGRES
    payer = "b" * 64
    sharer = "c" * 64
    referred = "d" * 64
    try:
        db.DB_NAME = str(tmp_path / "device-payment.db")
        db.USING_POSTGRES = False
        db.init_db()

        order_id = "XOANABCDEF123456"
        db.create_payment_order(
            "203.0.113.1", 20000, "https://vietqr.app/img",
            order_id=order_id, device_key=payer,
        )
        assert db.confirm_payment(order_id, "TX-DEVICE", 20000, 7, 3) == "paid"
        assert db.get_device_access(payer, 1)["remaining"] == 3

        code = db.get_or_create_device_referral(sharer)
        assert db.claim_device_referral(code, referred, 7, 1)
        assert db.get_device_access(sharer, 1)["remaining"] == 1
        assert not db.claim_device_referral(code, referred, 7, 1)
    finally:
        db.DB_NAME = old_name
        db.USING_POSTGRES = old_postgres


def test_migrates_and_attaches_legacy_paid_order(tmp_path):
    import sqlite3
    from app import database as db

    old_name = db.DB_NAME
    old_postgres = db.USING_POSTGRES
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute("""CREATE TABLE payment_orders (
        order_id TEXT PRIMARY KEY, ip TEXT, amount INTEGER, status TEXT,
        created_at TEXT, paid_at TEXT, expires_at TEXT, payment_url TEXT
    )""")
    connection.execute(
        "INSERT INTO payment_orders VALUES (?, ?, ?, 'paid', ?, ?, ?, ?)",
        ("XOANFEDCBA654321", "203.0.113.9", 20000,
         "2026-01-01T00:00:00", "2026-01-01T00:01:00",
         "2026-01-02T00:00:00", "https://vietqr.app/img"),
    )
    connection.commit()
    connection.close()

    try:
        db.DB_NAME = str(database_path)
        db.USING_POSTGRES = False
        db.init_db()
        device = "e" * 64
        assert db.get_payment_order("XOANFEDCBA654321")["device_key"] is None
        assert db.attach_paid_order_to_device("XOANFEDCBA654321", device, 7, 3)
        assert db.get_payment_order("XOANFEDCBA654321")["device_key"] == device
        assert db.get_device_access(device, 1)["remaining"] == 3
    finally:
        db.DB_NAME = old_name
        db.USING_POSTGRES = old_postgres
