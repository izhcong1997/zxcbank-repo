from config import PARTNER_API_KEY


def check_transfer(transfer):
    """Hand a transfer to the fictional ZXC fraud partner. No network call."""
    payload = {
        "partner": "zxc-fraud-partner.example",
        "api_key": PARTNER_API_KEY,
        "transfer": {
            "from_account": transfer.get("from_account"),
            "to_account": transfer.get("to_account"),
            "amount": transfer.get("amount"),
            "note": transfer.get("note"),
        },
    }
    return {"status": "stubbed", "partner": payload["partner"]}
