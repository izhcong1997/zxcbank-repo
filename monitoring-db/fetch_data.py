#!/usr/bin/env python3
"""Read GitHub and write data.json for the release control room. Read-only."""

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data.json"
API = "https://api.github.com"
DEFAULT_REPO = "izhcong1997/zxcbank-repo"
FIXES = re.compile(r"Fixes\s+#(\d+)", re.IGNORECASE)
SECRET = re.compile(
    r"(?:ghp_|github_pat_|sk-|AKIA|xox[baprs]-)[A-Za-z0-9_\-]+"
    r"|(?:token|password|secret)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
STEPS = [
    (1, "Code pushed", "Developer + Cursor", "Developer"),
    (2, "PR opened to main", "GitHub", "GitHub"),
    (3, "Checks run", "GitHub", "GitHub"),
    (4, "Security Analyst verdict", "Grok Bot team", "Security Analyst"),
    (5, "Fixer called", "Grok Bot team", "Fixer"),
    (6, "Cursor Cloud Agent fixing", "Developer + Cursor", "Fixer"),
    (7, "Fix PR opened", "GitHub", "Fixer"),
    (8, "Security re-check", "Grok Bot team", "Security Analyst"),
    (9, "Release Captain sign-off", "Grok Bot team", "Release Captain"),
    (10, "Human approved and merged", "People + audit", "Security approver"),
]
BOTS = [
    ("release-captain", "Release Captain", {9}),
    ("security-analyst", "Security Analyst", {4, 8}),
    ("fixer", "Fixer", {5, 6}),
    ("business-reporter", "Business Reporter", set()),
]
BAD_CHECKS = {"failure", "cancelled", "timed_out", "startup_failure"}
OPEN_CHECKS = {"in_progress", "queued", "pending", "waiting", "requested"}


def redact(text):
    return SECRET.sub("[redacted]", text or "")[:400]


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso(value):
    moment = parse_time(value)
    if not moment:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_minutes(value, now):
    moment = parse_time(value)
    if not moment:
        return None
    return (now - moment).total_seconds() / 60


def marker_jsons(body):
    found = []
    needle = "<!-- zxc-bot "
    start = 0
    body = body or ""
    while True:
        index = body.find(needle, start)
        if index < 0:
            break
        end = body.find("-->", index)
        if end < 0:
            break
        raw = body[index + len(needle) : end].strip()
        start = end + 3
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data["summary"] = redact(data.get("summary") or "")
            found.append(data)
    return found


def marker_state(marker):
    status = str((marker or {}).get("status") or "").lower()
    if status in {"failed", "blocked"}:
        return "blocked"
    if status in {"working", "done", "waiting"}:
        return status
    return None


def latest(markers, step=None, bot=None):
    chosen = []
    for marker in markers:
        if step is not None and marker.get("step") != step:
            continue
        if bot is not None and marker.get("bot") != bot:
            continue
        chosen.append(marker)
    chosen.sort(key=lambda item: item.get("at") or "")
    return chosen[-1] if chosen else None


def step(number, status, detail, at, url):
    _, name, lane, owner = STEPS[number - 1]
    return {
        "id": number,
        "name": name,
        "lane": lane,
        "owner": owner,
        "status": status,
        "detail": redact(detail),
        "at": iso(at),
        "url": url,
    }


def check_status(runs):
    if not runs:
        return "pending", "No check runs yet"
    named = []
    for run in runs:
        name = run.get("name") or "check"
        conclusion = run.get("conclusion") or run.get("status") or ""
        named.append((name, conclusion))
    failed = [name for name, conclusion in named if conclusion in BAD_CHECKS]
    if failed:
        return "blocked", "Failed: " + ", ".join(failed[:4])
    if any(conclusion in OPEN_CHECKS for _, conclusion in named):
        return "working", "Checks are still running"
    interesting = ("tests", "codeql", "ai scan", "dependabot", "copilot")
    seen = [name for name, _ in named if any(key in name.lower() for key in interesting)]
    return "done", "Passed: " + ", ".join(seen[:5] or ["checks"])


def is_fix(pr):
    branch = ((pr.get("head") or {}).get("ref") or "")
    match = FIXES.search(pr.get("body") or "")
    parent = int(match.group(1)) if match else None
    return branch.startswith("cursor/") or parent is not None, parent


def derive(pr, fix_prs, markers, runs, pr_url):
    labels = {label.get("name") for label in pr.get("labels") or []}
    fix_prs = sorted(fix_prs, key=lambda item: item.get("number") or 0)
    fix = fix_prs[-1] if fix_prs else None
    fix_url = (fix or {}).get("html_url") or pr_url
    created = pr.get("created_at")
    branch = ((pr.get("head") or {}).get("ref") or "")
    m4, m5, m6, m8, m9 = (latest(markers, step) for step in (4, 5, 6, 8, 9))
    checks, check_detail = check_status(runs)
    blocked_now = "security:blocked" in labels and "security:ok" not in labels
    step4 = "blocked" if blocked_now else marker_state(m4) or ("done" if "security:ok" in labels or "security:blocked" in labels else "pending")
    if step4 == "done" and blocked_now:
        step4 = "blocked"
    step5 = marker_state(m5)
    if not step5:
        if fix or "fix:in-progress" in labels:
            step5 = "done"
        elif "fix:requested" in labels:
            step5 = "working"
        else:
            step5 = "pending"
    step6 = marker_state(m6)
    if not step6:
        if fix:
            step6 = "done"
        elif "fix:in-progress" in labels:
            step6 = "working"
        else:
            step6 = "pending"
    step7 = "done" if fix else "pending"
    step8 = marker_state(m8)
    if not step8:
        if "security:ok" in labels and (fix or "security:blocked" in labels):
            step8 = "done"
        elif fix and blocked_now:
            step8 = "working"
        else:
            step8 = "pending"
    if "signoff:approved" in labels:
        step9 = "done"
    elif marker_state(m9) == "blocked":
        step9 = "blocked"
    elif "signoff:requested" in labels or m9:
        step9 = "waiting"
    else:
        step9 = "pending"
    if pr.get("merged_at"):
        step10 = "done"
    elif "signoff:approved" in labels:
        step10 = "working"
    else:
        step10 = "pending"
    v1 = (m4 or {}).get("summary") or ("Report v1 blocked" if step4 == "blocked" else "Security verdict")
    v2 = (m8 or {}).get("summary") or ("Report v2 clear" if step8 == "done" else "Security re-check")
    pack = (m9 or {}).get("summary") or "Sign-off pack is ready for a human"
    rows = [
        step(1, "done", f"Branch {branch}", created, pr_url),
        step(2, "done" if (pr.get("base") or {}).get("ref") == "main" else "pending", f"PR #{pr.get('number')} to {(pr.get('base') or {}).get('ref')}", created, pr_url),
        step(3, checks, check_detail, created, pr_url),
        step(4, step4, v1, (m4 or {}).get("at") or created, (m4 or {}).get("url") or pr_url),
        step(5, step5, (m5 or {}).get("summary") or "Fixer called", (m5 or {}).get("at"), (m5 or {}).get("url") or pr_url),
        step(6, step6, (m6 or {}).get("summary") or "Cursor Cloud Agent is writing the fix", (m6 or {}).get("at"), (m6 or {}).get("url") or pr_url),
        step(7, step7, f"Fix PR #{fix.get('number')}" if fix else "No fix PR yet", (fix or {}).get("created_at"), fix_url),
        step(8, step8, v2, (m8 or {}).get("at"), (m8 or {}).get("url") or pr_url),
        step(9, step9, pack, (m9 or {}).get("at"), (m9 or {}).get("url") or pr_url),
        step(10, step10, "Merged" if pr.get("merged_at") else "Waiting for a human to merge", pr.get("merged_at"), pr_url),
    ]
    reporter = latest(markers, bot="business-reporter")
    return rows, {
        "summary": (reporter or {}).get("summary") or "",
        "at": iso((reporter or {}).get("at")),
        "sent": "report:sent" in labels or reporter is not None,
    }


def catalog():
    return [{"id": number, "name": name, "lane": lane, "owner": owner} for number, name, lane, owner in STEPS]


def production_snapshot(repo, deployments, status_map, issues):
    version = None
    deployed_at = None
    if deployments is not None:
        for deployment in deployments:
            states = status_map.get(deployment.get("id")) or []
            latest = states[0] if states else {}
            if latest.get("state") == "success":
                version = deployment.get("ref") or None
                deployed_at = iso(latest.get("created_at") or deployment.get("created_at"))
                break
    incidents = []
    if issues is not None:
        for issue in issues:
            if "pull_request" in issue:
                continue
            labels = []
            for label in issue.get("labels") or []:
                name = label.get("name") if isinstance(label, dict) else str(label)
                if name:
                    labels.append(name)
            incidents.append(
                {
                    "number": issue.get("number"),
                    "title": redact(issue.get("title") or ""),
                    "url": issue.get("html_url") or "",
                    "labels": labels,
                    "opened_at": iso(issue.get("created_at")),
                }
            )
    return {
        "version": version,
        "deployed_at": deployed_at,
        "url": f"https://github.com/{repo}/deployments" if version else None,
        "incidents": incidents,
    }


def build(repo, pulls, comments, checks, events, runs, unavailable, now, production):
    by_id = {pr["number"]: pr for pr in pulls}
    children = {}
    primaries = []
    for pr in pulls:
        fix, parent = is_fix(pr)
        if fix and parent and parent in by_id:
            children.setdefault(parent, []).append(pr)
        elif not fix:
            primaries.append(pr)
        elif parent:
            children.setdefault(parent, []).append(pr)
        else:
            primaries.append(pr)
    releases = []
    audit = []
    for pr in primaries:
        number = pr["number"]
        pr_markers = []
        for owner_pr in [pr, *children.get(number, [])]:
            for comment in comments.get(owner_pr["number"], []):
                for marker in marker_jsons(comment.get("body") or ""):
                    marker.setdefault("at", comment.get("created_at"))
                    marker["url"] = comment.get("html_url")
                    pr_markers.append(marker)
                    audit.append({"at": iso(marker.get("at")), "kind": "marker", "text": f"{marker.get('bot')} step {marker.get('step')}: {marker.get('summary')}", "url": comment.get("html_url")})
        for event in events.get(number, []):
            kind = event.get("event")
            when = iso(event.get("created_at"))
            label = (event.get("label") or {}).get("name")
            if kind in {"labeled", "unlabeled"} and label:
                audit.append({"at": when, "kind": "label", "text": f"#{number} {kind} {label}", "url": pr.get("html_url")})
            elif kind == "merged":
                audit.append({"at": when, "kind": "merge", "text": f"#{number} merged", "url": pr.get("html_url")})
            elif kind == "reviewed":
                audit.append({"at": when, "kind": "approval", "text": f"#{number} review {redact(str(event.get('state') or ''))}", "url": pr.get("html_url")})
        steps, reporter = derive(pr, children.get(number, []), pr_markers, checks.get(number), pr.get("html_url"))
        releases.append({
            "number": number,
            "title": redact(pr.get("title") or ""),
            "url": pr.get("html_url"),
            "author": (pr.get("user") or {}).get("login") or "",
            "branch": (pr.get("head") or {}).get("ref") or "",
            "merged_at": iso(pr.get("merged_at")),
            "created_at": iso(pr.get("created_at")),
            "fix_prs": [{"number": item["number"], "title": redact(item.get("title") or ""), "url": item.get("html_url")} for item in children.get(number, [])],
            "steps": steps,
            "reporter": reporter,
        })
    releases.sort(key=lambda item: (item.get("merged_at") is not None, item.get("number") or 0))
    attention = []
    for release in releases:
        for item in release["steps"]:
            minutes = age_minutes(item.get("at"), now)
            reason = None
            if item["status"] == "working" and item["owner"] in {"Security Analyst", "Fixer", "Release Captain", "Business Reporter"} and minutes is not None and minutes > 20:
                reason = "Stalled for more than 20 minutes"
            elif item["status"] == "blocked" and minutes is not None and minutes > 60:
                reason = "Blocked for more than 1 hour"
            elif item["status"] == "waiting" and minutes is not None and minutes > 240:
                reason = "Waiting for sign-off for more than 4 hours"
            if reason:
                owner = "Security approver" if item["id"] == 9 and item["status"] == "waiting" else item["owner"]
                attention.append({"release": release["number"], "title": release["title"], "step": item["name"], "reason": reason, "owner": owner, "url": item.get("url") or release["url"], "at": item.get("at")})
    bots = []
    all_markers = []
    for group in comments.values():
        for comment in group:
            for marker in marker_jsons(comment.get("body") or ""):
                marker.setdefault("at", comment.get("created_at"))
                all_markers.append(marker)
    for bot_id, name, owned in BOTS:
        mine = [marker for marker in all_markers if marker.get("bot") == bot_id]
        mine.sort(key=lambda item: item.get("at") or "")
        last = mine[-1] if mine else None
        working_releases = set()
        stalled = False
        for release in releases:
            for item in release["steps"]:
                if item["id"] not in owned:
                    continue
                if item["status"] in {"working", "waiting"}:
                    working_releases.add(release["number"])
                minutes = age_minutes(item.get("at"), now)
                if item["status"] == "working" and minutes is not None and minutes > 20:
                    stalled = True
        working = len(working_releases)
        status = "stalled" if stalled else marker_state(last) or ("working" if working else "idle")
        bots.append({"id": bot_id, "name": name, "last_action": (last or {}).get("summary") or "No action yet", "at": iso((last or {}).get("at")), "status": status, "working_on": working})
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)
    merged = [item for item in releases if item.get("merged_at")]
    hours = []
    for item in merged:
        opened = parse_time(item.get("created_at"))
        closed = parse_time(item.get("merged_at"))
        if opened and closed and closed >= month:
            hours.append((closed - opened).total_seconds() / 3600)
    pipeline = []
    for run in runs or []:
        if run.get("status") != "completed":
            continue
        start = parse_time(run.get("run_started_at") or run.get("created_at"))
        end = parse_time(run.get("updated_at"))
        if start and end and start >= month and end >= start:
            pipeline.append((end - start).total_seconds() / 60)
    tiles = {
        "in_flight": sum(1 for item in releases if not item.get("merged_at")),
        "blocked": sum(1 for item in releases if any(step["status"] == "blocked" for step in item["steps"])),
        "waiting_signoff": sum(1 for item in releases if any(step["id"] == 9 and step["status"] == "waiting" for step in item["steps"])),
        "merged_this_week": sum(1 for item in merged if parse_time(item["merged_at"]) and parse_time(item["merged_at"]) >= week),
        "avg_hours_open_to_merge": round(sum(hours) / len(hours), 1) if hours else None,
        "avg_pipeline_minutes": round(sum(pipeline) / len(pipeline), 1) if pipeline else None,
    }
    audit = [item for item in audit if item.get("at")]
    audit.sort(key=lambda item: item["at"], reverse=True)
    return {
        "version": 1,
        "generated_at": iso(now),
        "repository": repo,
        "source": "github",
        "unavailable": sorted(set(unavailable)),
        "tiles": tiles,
        "production": production,
        "lanes": ["Developer + Cursor", "GitHub", "Grok Bot team", "People + audit"],
        "steps": catalog(),
        "releases": releases,
        "bots": bots,
        "attention": attention,
        "audit": audit[:30],
    }


def github_get(session, url, params=None):
    try:
        response = session.get(url, params=params or {}, timeout=30)
    except requests.RequestException:
        return None, "not available"
    if response.status_code != 200:
        return None, "not available"
    try:
        return response.json(), None
    except ValueError:
        return None, "not available"


def load_github(repo, token):
    session = requests.Session()
    session.headers["Accept"] = "application/vnd.github+json"
    session.headers["X-GitHub-Api-Version"] = "2022-11-28"
    session.headers["User-Agent"] = "zxc-release-control-room"
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    unavailable = []
    now = datetime.now(timezone.utc)
    opened, problem = github_get(session, f"{API}/repos/{repo}/pulls", {"state": "open", "per_page": 50})
    closed, closed_problem = github_get(session, f"{API}/repos/{repo}/pulls", {"state": "closed", "per_page": 50, "sort": "updated", "direction": "desc"})
    if problem:
        unavailable.append("pulls")
    if closed_problem:
        unavailable.append("pulls")
    month = now - timedelta(days=30)
    pulls = list(opened or [])
    for pr in closed or []:
        merged = parse_time(pr.get("merged_at"))
        if merged and merged >= month:
            pulls.append(pr)
    comments, checks, events = {}, {}, {}
    for pr in pulls[:40]:
        number = pr["number"]
        body, problem = github_get(session, f"{API}/repos/{repo}/issues/{number}/comments", {"per_page": 100})
        comments[number] = body or []
        if problem:
            unavailable.append("comments")
        sha = (pr.get("head") or {}).get("sha")
        runs, problem = github_get(session, f"{API}/repos/{repo}/commits/{sha}/check-runs", {"per_page": 50}) if sha else (None, "not available")
        checks[number] = (runs or {}).get("check_runs") if isinstance(runs, dict) else None
        if problem or checks[number] is None:
            checks[number] = []
            unavailable.append("checks")
        timeline, problem = github_get(session, f"{API}/repos/{repo}/issues/{number}/events", {"per_page": 100})
        events[number] = timeline or []
        if problem:
            unavailable.append("events")
    actions, problem = github_get(session, f"{API}/repos/{repo}/actions/runs", {"per_page": 50})
    action_runs = (actions or {}).get("workflow_runs") if isinstance(actions, dict) else []
    if problem:
        unavailable.append("actions")
        action_runs = []
    _, problem = github_get(session, f"{API}/repos/{repo}/code-scanning/alerts", {"state": "open", "per_page": 1})
    if problem:
        unavailable.append("code_scanning")
    deployments, problem = github_get(
        session,
        f"{API}/repos/{repo}/deployments",
        {"environment": "production", "per_page": 20},
    )
    status_map = {}
    if problem or not isinstance(deployments, list):
        unavailable.append("deployments")
        deployments = None
    else:
        for deployment in deployments[:10]:
            statuses, problem = github_get(
                session,
                f"{API}/repos/{repo}/deployments/{deployment.get('id')}/statuses",
                {"per_page": 5},
            )
            if problem or not isinstance(statuses, list):
                unavailable.append("deployments")
                deployments = None
                break
            status_map[deployment.get("id")] = statuses
    issues, problem = github_get(
        session,
        f"{API}/repos/{repo}/issues",
        {"state": "open", "labels": "incident", "per_page": 20},
    )
    if problem or not isinstance(issues, list):
        unavailable.append("incidents")
        issues = None
    production = production_snapshot(repo, deployments, status_map, issues)
    return build(repo, pulls, comments, checks, events, action_runs or [], unavailable, now, production)


def write_data():
    repo = os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO
    token = os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        print("GITHUB_TOKEN is not set. Writing an empty snapshot.")
    payload = load_github(repo, token)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.name} for {repo}")


def main():
    parser = argparse.ArgumentParser(description="Build release control room data.json")
    parser.add_argument("--watch", type=int, default=0, help="Re-fetch every N seconds")
    args = parser.parse_args()
    while True:
        try:
            write_data()
        except Exception as exc:
            print(f"Fetch failed: {exc.__class__.__name__}")
            if not args.watch:
                raise
        if args.watch <= 0:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
