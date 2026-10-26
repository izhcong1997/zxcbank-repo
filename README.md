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

## Incident demo

`v1.0` is the last good release. `release/v1.1`, tagged `v1.1`, rejects an amount with cents such as `25.50` with HTTP 500 and error `TX-503`. `tests/test_health.py` passes on `v1.0` and fails on `v1.1`.

1. Deploy `v1.1`. In Actions, open Deploy and run it with that version. Or comment `/deploy v1.1` on an issue labelled `incident` as `izhcong1997`. Any other comment is ignored. A version that is not an existing tag is rejected on the issue.
2. Run Health check. It checks out the deployed tag and runs `tests/test_health.py`. On `v1.1` the test fails, and ZXC Pager opens `INC-0413: Transfers failing (TX-503) on payments-api` with labels `incident` and `sev1`.
3. The control room Production panel shows the live version, when it was deployed, and the open incident with its labels and age.
4. Roll back by deploying `v1.0` the same way.
5. Run Health check again. It comments `Health check passing on v1.0` and closes the incident.

The 10-minute health-check schedule is commented out in `.github/workflows/health-check.yml`. Uncomment it when the demo should run on its own. If nothing has been deployed, Health check prints `Nothing deployed yet` and does not open an incident.

`ops/ownership.yml` names the on-call for each service. `.github/CODEOWNERS` maps the payment files to `@izhcong1997`. ZXC Pager posts its alert only when `GROK_INCIDENT_URL` and `GROK_INCIDENT_KEY` are set.
