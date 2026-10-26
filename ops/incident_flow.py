"""Deploy, health-check, and page the ZXCBank demo. Talks to GitHub. Never commits."""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SGT = timezone(timedelta(hours=8))
VERSION_RE = re.compile(r"^v\d+\.\d+$")
DEPLOYER = "izhcong1997"
INCIDENT_NUMBER = "INC-0413"
INCIDENT_TITLE = "INC-0413: Transfers failing (TX-503) on payments-api"
SERVICE = "payments-api"
METRIC = "transfer error rate 8% > 1% threshold"
MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def sgt_now(now=None):
    current = now or datetime.now(SGT)
    return (
        f"{current.day:02d} {MONTHS[current.month - 1]} {current.year}, "
        f"{current.hour:02d}:{current.minute:02d} SGT"
    )


def reject_message(version):
    shown = version or "(empty)"
    return (
        f"Rejected {shown}. That tag does not exist. "
        "Production only accepts an existing tag, such as v1.0 or v1.1."
    )


def deploy_message(version, when):
    return f"Deployed {version} to production at {when}"


def health_message(version):
    return f"Health check passing on {version}"


class GitHub:
    def __init__(self, repo, token, opener=None):
        self.repo = repo
        self.token = token
        self.opener = opener or urllib.request.urlopen

    def request(self, method, path, body=None):
        url = f"https://api.github.com/repos/{self.repo}{path}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "zxc-incident-demo")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            response = self.opener(req, timeout=30)
        except urllib.error.HTTPError as err:
            return err.code, _decode(err.read().decode())
        with response as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return status, _decode(resp.read().decode())


def _decode(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"message": raw}


def _expect(status, payload, ok, action):
    if status not in ok:
        message = payload.get("message", status) if isinstance(payload, dict) else status
        raise SystemExit(f"Could not {action}: {message}")
    return payload


def tag_exists(gh, version):
    status, payload = gh.request(
        "GET", "/git/ref/tags/" + urllib.parse.quote(version, safe="")
    )
    if status == 200:
        return True
    if status == 404:
        return False
    _expect(status, payload, (200,), f"look up tag {version}")
    return False


def comment(gh, issue_number, text):
    payload = _expect(
        *gh.request("POST", f"/issues/{issue_number}/comments", {"body": text}),
        (200, 201),
        f"comment on issue #{issue_number}",
    )
    return payload


def open_incidents(gh):
    status, payload = gh.request("GET", "/issues?state=open&labels=incident&per_page=20")
    payload = _expect(status, payload, (200,), "list incident issues")
    if not isinstance(payload, list):
        raise SystemExit("Could not list incident issues: unexpected response")
    return [item for item in payload if "pull_request" not in item]


def find_production(gh):
    status, payload = gh.request(
        "GET", "/deployments?environment=production&per_page=20"
    )
    payload = _expect(status, payload, (200,), "list production deployments")
    if not isinstance(payload, list):
        raise SystemExit("Could not list production deployments: unexpected response")
    current = None
    previous = None
    for deployment in payload:
        state = _latest_state(gh, deployment["id"])
        if current is None:
            if state == "success":
                current = deployment.get("ref") or ""
            continue
        if state in ("success", "inactive") and deployment.get("ref"):
            previous = deployment["ref"]
            break
    return current or None, previous


def _latest_state(gh, deployment_id):
    status, payload = gh.request(
        "GET", f"/deployments/{deployment_id}/statuses?per_page=5"
    )
    payload = _expect(status, payload, (200,), "read deployment status")
    if not isinstance(payload, list) or not payload:
        return ""
    return payload[0].get("state") or ""


def create_production_deployment(gh, version):
    created = _expect(
        *gh.request(
            "POST",
            "/deployments",
            {
                "ref": version,
                "environment": "production",
                "auto_merge": False,
                "required_contexts": [],
                "description": f"ZXCBank demo deploy {version}",
                "production_environment": True,
            },
        ),
        (200, 201, 202),
        "create the deployment",
    )
    deployment_id = created.get("id")
    if not deployment_id:
        raise SystemExit("Could not create the deployment: missing id")
    _expect(
        *gh.request(
            "POST",
            f"/deployments/{deployment_id}/statuses",
            {
                "state": "success",
                "environment": "production",
                "description": f"Deployed {version}",
                "auto_inactive": True,
            },
        ),
        (200, 201),
        "mark the deployment successful",
    )


def _comment_if_present(gh, issue_number, text):
    if issue_number:
        comment(gh, issue_number, text)


def deploy(gh, event_name, event, version_input, when):
    issue_number = None
    if event_name == "issue_comment":
        issue = (event or {}).get("issue") or {}
        if issue.get("pull_request"):
            print("Ignoring comment on a pull request")
            return 0
        login = ((event or {}).get("comment") or {}).get("user", {}).get("login", "")
        if login != DEPLOYER:
            print(f"Ignoring comment from {login or 'unknown'}")
            return 0
        labels = [label.get("name") for label in issue.get("labels") or []]
        if "incident" not in labels:
            print("Ignoring comment on an issue without the incident label")
            return 0
        body = ((event or {}).get("comment") or {}).get("body") or ""
        body = body.replace("\r\n", "\n").strip()
        match = re.fullmatch(r"/deploy (v\d+\.\d+)", body)
        if not match:
            print("Ignoring comment that is not a deploy command")
            return 0
        version = match.group(1)
        issue_number = issue.get("number")
    else:
        version = (version_input or "").strip()
        incidents = open_incidents(gh)
        if incidents:
            issue_number = incidents[0]["number"]

    if not VERSION_RE.fullmatch(version or "") or not tag_exists(gh, version):
        message = reject_message(version)
        print(message)
        _comment_if_present(gh, issue_number, message)
        return 1

    create_production_deployment(gh, version)
    message = deploy_message(version, when)
    print(message)
    _comment_if_present(gh, issue_number, message)
    return 0


def lookup(gh, write_output):
    current, previous = find_production(gh)
    if not current:
        print("Nothing deployed yet")
        write_output("deployed", "false")
        return 0
    write_output("deployed", "true")
    write_output("version", current)
    write_output("previous", previous or "none")
    print(f"Production is {current}")
    return 0


def resolve(gh, version):
    version = (version or "").strip()
    if not version:
        raise SystemExit("Deployed version is missing")
    incidents = open_incidents(gh)
    if not incidents:
        print("No open incident")
        return 0
    text = health_message(version)
    for issue in incidents:
        comment(gh, issue["number"], text)
        _expect(
            *gh.request("PATCH", f"/issues/{issue['number']}", {"state": "closed"}),
            (200,),
            f"close issue #{issue['number']}",
        )
        print(f"Closed #{issue['number']}")
    return 0


def ensure_label(gh, name, color):
    status, payload = gh.request("GET", "/labels/" + urllib.parse.quote(name, safe=""))
    if status == 200:
        return
    if status != 404:
        _expect(status, payload, (200, 404), f"read label {name}")
    _expect(
        *gh.request("POST", "/labels", {"name": name, "color": color}),
        (200, 201),
        f"create label {name}",
    )


def post_alert(payload, url, key, opener=None):
    if not url or not key:
        print("Skipping POST because GROK_INCIDENT_URL or GROK_INCIDENT_KEY is empty")
        return False
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "zxc-incident-demo")
    try:
        response = opener(req, timeout=20)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"Incident POST failed: {err.code}") from None
    except urllib.error.URLError:
        raise SystemExit("Incident POST failed") from None
    with response as resp:
        status = getattr(resp, "status", None) or resp.getcode()
    if status not in (200, 201, 202, 204):
        raise SystemExit(f"Incident POST failed: {status}")
    print("Posted the incident alert")
    print(json.dumps(payload))
    return True


def alert_payload(version, previous, run_link):
    return {
        "incident_number": INCIDENT_NUMBER,
        "title": INCIDENT_TITLE,
        "service": SERVICE,
        "severity": "sev1",
        "deployed_version": version or "none",
        "previous_good_version": previous or "none",
        "run_link": run_link or "",
    }


def issue_body(version, previous, run_link, when):
    return "\n".join(
        [
            "PagerDuty alert",
            "",
            f"Service: {SERVICE}",
            f"Metric: {METRIC}",
            f"Started at: {when}",
            f"Deployed version: {version or 'none'}",
            f"Previous good version: {previous or 'none'}",
            f"Run: {run_link or ''}",
        ]
    )


def page(gh, deployed, previous, run_link, when, url, key, opener=None):
    incidents = open_incidents(gh)
    if incidents:
        print(f"Incident already open: #{incidents[0]['number']}")
        return 0
    if not (deployed or "").strip():
        deployed, found_previous = find_production(gh)
        if not (previous or "").strip():
            previous = found_previous
    ensure_label(gh, "incident", "d73a4a")
    ensure_label(gh, "sev1", "b60205")
    payload = alert_payload(deployed, previous, run_link)
    created = _expect(
        *gh.request(
            "POST",
            "/issues",
            {
                "title": INCIDENT_TITLE,
                "body": issue_body(deployed, previous, run_link, when),
                "labels": ["incident", "sev1"],
            },
        ),
        (200, 201),
        "open the incident",
    )
    print(f"Opened #{created.get('number')} {INCIDENT_TITLE}")
    post_alert(payload, url, key, opener=opener)
    return 0


def _write_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _github_from_env():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo:
        raise SystemExit("GITHUB_REPOSITORY is not set")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set")
    return GitHub(repo, token)


def main(argv):
    if len(argv) != 2 or argv[1] not in ("deploy", "lookup", "resolve", "page"):
        raise SystemExit("Usage: incident_flow.py deploy|lookup|resolve|page")
    command = argv[1]
    gh = _github_from_env()
    if command == "deploy":
        event = None
        event_name = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
        if event_name == "issue_comment":
            with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
                event = json.load(handle)
        return deploy(
            gh,
            event_name,
            event,
            os.environ.get("INPUT_VERSION", ""),
            sgt_now(),
        )
    if command == "lookup":
        return lookup(gh, _write_output)
    if command == "resolve":
        return resolve(gh, os.environ.get("DEPLOYED_VERSION", ""))
    return page(
        gh,
        os.environ.get("DEPLOYED_VERSION", ""),
        os.environ.get("PREVIOUS_GOOD_VERSION", ""),
        os.environ.get("RUN_LINK", ""),
        sgt_now(),
        os.environ.get("GROK_INCIDENT_URL", ""),
        os.environ.get("GROK_INCIDENT_KEY", ""),
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv))
