from datetime import datetime, timezone

import mongomock
import pytest

from app import app


@pytest.fixture
def transfers(monkeypatch):
    collection = mongomock.MongoClient()["zxc_bank_demo"]["transfers"]
    monkeypatch.setattr("app.get_transfers", lambda: collection)
    return collection


@pytest.fixture
def client(transfers):
    app.testing = True
    with app.test_client() as test_client:
        yield test_client


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    page = response.data.decode()
    assert "Hello from ZXC Bank" in page
    assert "Send money" in page
    assert 'name="from_account"' in page
    assert 'name="to_account"' in page
    assert 'name="amount"' in page
    assert 'name="note"' in page


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


@pytest.mark.parametrize("amount", ["0", "-5", "10000.01", "abc", "", "10,000"])
def test_rejects_invalid_amount(client, transfers, amount):
    response = client.post(
        "/transfer",
        data={
            "from_account": "12345678",
            "to_account": "87654321",
            "amount": amount,
            "note": "rent",
        },
    )
    assert response.status_code == 400
    assert b"Transfer sent" not in response.data
    assert b"positive number" in response.data
    assert transfers.count_documents({}) == 0


@pytest.mark.parametrize(
    "from_account,to_account",
    [
        ("1234567", "87654321"),
        ("1234567890123", "87654321"),
        ("1234567a", "87654321"),
        ("12345678", "8765432"),
        ("12345678", "account1"),
    ],
)
def test_rejects_invalid_account(client, transfers, from_account, to_account):
    response = client.post(
        "/transfer",
        data={
            "from_account": from_account,
            "to_account": to_account,
            "amount": "10",
            "note": "",
        },
    )
    assert response.status_code == 400
    assert b"8 to 12 digits" in response.data
    assert transfers.count_documents({}) == 0


def test_transfer_is_saved_and_shows_last_five(client, transfers, monkeypatch):
    tick = {"n": 0}

    def fake_now():
        tick["n"] += 1
        return datetime(2026, 10, 23, 9, 0, tick["n"], tzinfo=timezone.utc)

    monkeypatch.setattr("app.utc_now", fake_now)

    for index in range(6):
        response = client.post(
            "/transfer",
            data={
                "from_account": "12345678",
                "to_account": "123456789012",
                "amount": str(index + 1),
                "note": f"n{index}",
            },
        )
        assert response.status_code == 200

    page = response.data.decode()
    assert "Transfer sent" in page
    assert page.count("Completed") == 5
    assert "n5" in page
    assert "n1" in page
    assert "n0" not in page

    saved = transfers.find_one({"note": "n5"})
    assert saved["status"] == "Completed"
    assert saved["from_account"] == "12345678"
    assert saved["to_account"] == "123456789012"
    assert saved["amount"] == 6
    stored = saved["timestamp"]
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    assert stored == datetime(2026, 10, 23, 9, 0, 6, tzinfo=timezone.utc)


def test_upper_amount_boundary(client, transfers):
    response = client.post(
        "/transfer",
        data={
            "from_account": "12345678",
            "to_account": "87654321",
            "amount": "10000",
            "note": "",
        },
    )
    assert response.status_code == 200
    assert transfers.find_one()["amount"] == 10000
