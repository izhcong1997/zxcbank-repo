"""Compare two control-room snapshots and tell the Release Captain. Never prints secrets."""

import json
import os
import sys
import urllib.error
import urllib.request


def is_timestamp(key):
    return isinstance(key, str) and (key == "at" or key.endswith("_at"))


def strip_times(value):
    if isinstance(value, dict):
        return {
            key: strip_times(item)
            for key, item in value.items()
            if not is_timestamp(key)
        }
    if isinstance(value, list):
        return [strip_times(item) for item in value]
    return value


def incidents_of(data):
    production = data.get("production") or {}
    found = list(production.get("incidents") or [])
    if found:
        return found
    return list(data.get("incidents") or [])


def production_of(data):
    production = dict(data.get("production") or {})
    production.pop("incidents", None)
    return production


def release_map(data):
    found = {}
    for release in data.get("releases") or []:
        found[release.get("number")] = release
    return found


def one_line(parts):
    text = "; ".join(part for part in parts if part)
    text = " ".join(text.split())
    if len(text) > 300:
        text = text[:297] + "..."
    return text or "Control room changed"


def summarize(old, new):
    parts = []
    old_version = production_of(old).get("version")
    new_version = production_of(new).get("version")
    if old_version != new_version:
        parts.append(f"Production {old_version or 'nothing'} -> {new_version or 'nothing'}")
    elif strip_times(production_of(old)) != strip_times(production_of(new)):
        parts.append("Production changed")

    old_incidents = {item.get("number"): item for item in incidents_of(old)}
    new_incidents = {item.get("number"): item for item in incidents_of(new)}
    for number in sorted(set(new_incidents) - set(old_incidents), key=lambda item: item or 0):
        parts.append(f"Incident #{number} opened")
    for number in sorted(set(old_incidents) - set(new_incidents), key=lambda item: item or 0):
        parts.append(f"Incident #{number} closed")
    for number in sorted(set(old_incidents) & set(new_incidents), key=lambda item: item or 0):
        if strip_times(old_incidents[number]) != strip_times(new_incidents[number]):
            parts.append(f"Incident #{number} changed")

    old_releases = release_map(old)
    new_releases = release_map(new)
    for number in sorted(set(new_releases) - set(old_releases), key=lambda item: item or 0):
        parts.append(f"Release #{number} added")
    for number in sorted(set(old_releases) - set(new_releases), key=lambda item: item or 0):
        parts.append(f"Release #{number} removed")
    for number in sorted(set(old_releases) & set(new_releases), key=lambda item: item or 0):
        if strip_times(old_releases[number]) == strip_times(new_releases[number]):
            continue
        old_steps = {step.get("id"): step for step in old_releases[number].get("steps") or []}
        new_steps = {step.get("id"): step for step in new_releases[number].get("steps") or []}
        named = False
        for step_id in sorted(set(old_steps) | set(new_steps), key=lambda item: item or 0):
            before = strip_times(old_steps.get(step_id) or {})
            after = strip_times(new_steps.get(step_id) or {})
            if before != after:
                status = (new_steps.get(step_id) or {}).get("status") or "changed"
                parts.append(f"Release #{number} step {step_id} is {status}")
                named = True
                break
        if not named:
            parts.append(f"Release #{number} changed")

    if strip_times(old.get("attention")) != strip_times(new.get("attention")):
        count = len(new.get("attention") or [])
        parts.append(f"Needs attention is {count}")
    if strip_times(old.get("steps")) != strip_times(new.get("steps")):
        parts.append("Steps changed")
    return one_line(parts)


def changed(old, new):
    watched = (
        ("releases", release_map(old), release_map(new)),
        ("steps", old.get("steps"), new.get("steps")),
        ("attention", old.get("attention"), new.get("attention")),
        ("production", production_of(old), production_of(new)),
        ("incidents", incidents_of(old), incidents_of(new)),
    )
    return any(strip_times(before) != strip_times(after) for _name, before, after in watched)


def load(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit("Control room data is not an object")
    return data


def write_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def compare_files(previous_path, current_path):
    old = load(previous_path)
    new = load(current_path)
    did_change = changed(old, new)
    summary = summarize(old, new) if did_change else ""
    write_output("changed", "true" if did_change else "false")
    write_output("summary", summary)
    print("changed" if did_change else "unchanged")
    if summary:
        print(summary)
    return 0


def post_alert(url, key, summary, opener=None):
    if not url or not key:
        print("Skipping POST because GROK_CAPTAIN_URL or GROK_CAPTAIN_KEY is empty")
        return 0
    payload = {"reason": "control room changed", "summary": summary or "Control room changed"}
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
    )
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "zxc-release-control-room")
    try:
        response = opener(request, timeout=20)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"Captain POST failed: {err.code}") from None
    except urllib.error.URLError:
        raise SystemExit("Captain POST failed") from None
    with response as resp:
        status = getattr(resp, "status", None) or resp.getcode()
    if status not in (200, 201, 202, 204):
        raise SystemExit(f"Captain POST failed: {status}")
    print("Posted the control room change")
    print(json.dumps(payload))
    return 0


def main(argv):
    if len(argv) == 4 and argv[1] == "compare":
        return compare_files(argv[2], argv[3])
    if len(argv) == 2 and argv[1] == "post":
        return post_alert(
            os.environ.get("GROK_CAPTAIN_URL", ""),
            os.environ.get("GROK_CAPTAIN_KEY", ""),
            os.environ.get("SUMMARY", ""),
        )
    raise SystemExit("Usage: compare_control_room.py compare OLD.json NEW.json | post")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
