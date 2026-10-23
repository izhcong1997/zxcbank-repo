#!/usr/bin/env python3
"""Block rm -rf and deleting this repository."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG = Path(__file__).resolve().parent / "audit.log"
DENY_TEXT = "Blocked by ZXCBank guardrail. Ask a human to do this after a backup."
REPO_NAMES = {".git", "cursor-guard-demo", "zxc-bank-demo"}


def log_event(decision, command):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    detail = (command or "").replace("\r", " ").replace("\n", " ")
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {decision} beforeShellExecution {detail}\n")
    except OSError:
        return


def _segments(command):
    return re.split(r"&&|\|\||;", command or "")


def _rm_invocations(command):
    for segment in _segments(command):
        tokens = segment.split()
        for index, token in enumerate(tokens):
            bare = token.strip("'\"")
            if bare.rsplit("/", 1)[-1] != "rm":
                continue
            yield [item.strip("'\"") for item in tokens[index + 1 :]]


def is_rm_rf(command):
    for args in _rm_invocations(command):
        force = False
        recursive = False
        for arg in args:
            if arg == "--":
                break
            if arg == "--force":
                force = True
            elif arg == "--recursive":
                recursive = True
            elif arg.startswith("-") and not arg.startswith("--"):
                letters = arg[1:]
                if "f" in letters or "F" in letters:
                    force = True
                if "r" in letters or "R" in letters:
                    recursive = True
        if force and recursive:
            return True
    return False


def deletes_repository(command):
    if re.search(r"\bgh\s+repo\s+delete\b", command or ""):
        return True
    for args in _rm_invocations(command):
        for arg in args:
            if arg == "--" or (arg.startswith("-") and arg != "-"):
                continue
            bare = arg.rstrip("/")
            base = bare.rsplit("/", 1)[-1]
            if bare in {".", "./", ".git"} or base in REPO_NAMES:
                return True
    return False


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    command = data.get("command") or "" if isinstance(data, dict) else ""
    deny = is_rm_rf(command) or deletes_repository(command)
    log_event("DENY" if deny else "ALLOW", command)
    if deny:
        payload = {
            "permission": "deny",
            "user_message": DENY_TEXT,
            "agent_message": DENY_TEXT,
        }
    else:
        payload = {"permission": "allow"}
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
