# zxc-bank-demo

Fictional demo app for ZXCBank. It does not move real money.

`main` is the safe version: a short transfer form that stores a record in MongoDB.

The `feature/transfer-search` branch contains intentional vulnerabilities for security-review demos. Do not merge that branch to production.

## Run

Python 3.11 or newer.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Fill in `MONGODB_URI` in `.env`, then:

```bash
flask --app app run
```

## Tests

```bash
pytest
```
