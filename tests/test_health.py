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


def test_transfer_with_cents_succeeds(client):
    response = client.post(
        "/transfer",
        data={
            "from_account": "12345678",
            "to_account": "87654321",
            "amount": "25.50",
            "note": "cents",
        },
    )
    assert response.status_code == 200
    assert b"Transfer sent" in response.data
