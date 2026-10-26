import re
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

from db import get_transfers

app = Flask(__name__)

ACCOUNT_RE = re.compile(r"^\d{8,12}$")
AMOUNT_RE = re.compile(r"^\d+(?:\.\d{1,2})?$")


def utc_now():
    return datetime.now(timezone.utc)


def parse_transfer(form):
    errors = []
    from_account = (form.get("from_account") or "").strip()
    to_account = (form.get("to_account") or "").strip()
    amount_raw = (form.get("amount") or "").strip()
    note = (form.get("note") or "").strip()

    if not ACCOUNT_RE.fullmatch(from_account):
        errors.append("From account must be 8 to 12 digits.")
    if not ACCOUNT_RE.fullmatch(to_account):
        errors.append("To account must be 8 to 12 digits.")

    amount = None
    if not AMOUNT_RE.fullmatch(amount_raw):
        errors.append("Amount must be a positive number up to 10000 SGD.")
    else:
        amount = float(amount_raw)
        if amount <= 0 or amount > 10000:
            errors.append("Amount must be a positive number up to 10000 SGD.")
            amount = None

    parsed = {
        "from_account": from_account,
        "to_account": to_account,
        "amount": amount if amount is not None else amount_raw,
        "note": note,
    }
    return parsed, errors, amount


def recent_transfers():
    rows = []
    cursor = get_transfers().find().sort("timestamp", -1).limit(5)
    for doc in cursor:
        stamp = doc["timestamp"]
        if isinstance(stamp, datetime):
            stamp = stamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        rows.append(
            {
                "from_account": doc["from_account"],
                "to_account": doc["to_account"],
                "amount": f"{doc['amount']:.2f}",
                "note": doc.get("note", ""),
                "status": doc["status"],
                "timestamp": stamp,
            }
        )
    return rows


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/transfer")
def transfer():
    parsed, errors, amount = parse_transfer(request.form)
    if errors:
        return render_template("index.html", errors=errors, form=parsed), 400

    if isinstance(amount, float) and amount != int(amount):  # INTENTIONAL BUG FOR INCIDENT DEMO
        return jsonify({"error": "TX-503"}), 500

    get_transfers().insert_one(
        {
            "from_account": parsed["from_account"],
            "to_account": parsed["to_account"],
            "amount": amount,
            "note": parsed["note"],
            "timestamp": utc_now(),
            "status": "Completed",
        }
    )
    return render_template(
        "index.html",
        message="Transfer sent",
        transfers=recent_transfers(),
        form=parsed,
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
