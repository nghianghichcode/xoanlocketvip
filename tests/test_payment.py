from urllib.parse import parse_qs, urlparse

from app.services.payment import build_vietqr_url, extract_order_id, generate_order_id


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


def test_extract_order_from_official_sepay_fields():
    payload = {
        "code": None,
        "content": "XOAN0123456789AB chuyen tien",
        "description": "incoming transfer",
    }
    assert extract_order_id(payload, "XOAN") == "XOAN0123456789AB"


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
