#!/usr/bin/env python3
"""ZXCBank guardrail for destructive commands, database drops, and .env reads."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG = Path(__file__).resolve().parent / "audit.log"
DENY_TEXT = "Blocked by ZXCBank guardrail. Ask a human to do this after a backup."

DB_PATTERNS = (
    re.compile(r"dropDatabase"),
    re.compile(r"\.drop\s*\(\s*\)"),
    re.compile(r"\bdeleteMany\s*\(\s*\{\s*\}\s*\)"),
    re.compile(r"\bremove\s*\(\s*\{\s*\}\s*\)"),
)
PROJECT_DIRS = {"zxc-bank-demo", "cursor-guard-demo"}


def redact(text):
    text = str(text).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"mongodb(?:\+srv)?://\S+", "mongodb://<redacted>", text)
    text = re.sub(
        r"(?i)(api[_-]?key|password|secret|token)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        text,
    )
    if len(text) > 400:
        text = text[:400] + "..."
    return text


def log_event(decision, event, detail):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{stamp} {decision} {event} {redact(detail)}\n"
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return


def dangerous_db_text(text):
    return any(pattern.search(text or "") for pattern in DB_PATTERNS)


def _segments(command):
    return re.split(r"&&|\|\||;", command or "")


def dangerous_rm(command):
    for segment in _segments(command):
        tokens = segment.split()
        for index, token in enumerate(tokens):
            bare = token.strip("'\"")
            if bare.rsplit("/", 1)[-1] != "rm":
                continue
            if _rm_args_dangerous([item.strip("'\"") for item in tokens[index + 1 :]]):
                return True
    return False


def _rm_args_dangerous(args):
    recursive = False
    operands = []
    flags_done = False
    for arg in args:
        if not flags_done and arg == "--":
            flags_done = True
            continue
        if not flags_done and arg.startswith("-") and arg != "-":
            if arg == "--recursive" or (
                arg.startswith("--") and arg != "--recursive"
            ):
                if arg == "--recursive":
                    recursive = True
            elif "r" in arg[1:] or "R" in arg[1:]:
                recursive = True
            continue
        operands.append(arg)
    if recursive:
        return True
    for operand in operands:
        target = operand.rstrip("/")
        if target in {".", "./", "./."}:
            return True
        if target.rsplit("/", 1)[-1] in PROJECT_DIRS:
            return True
    return False


def dangerous_git(command):
    for segment in _segments(command):
        if re.search(r"\bgit\s+push\b", segment):
            if re.search(r"--force(?!-)", segment):
                return True
            for token in segment.split():
                if token.startswith("-") and not token.startswith("--") and "f" in token[1:]:
                    return True
        if re.search(r"\bgit\s+reset\b", segment) and re.search(r"--hard\b", segment):
            return True
        if re.search(r"\bgit\s+clean\b", segment) and _git_clean_fd(segment):
            return True
    return False


def _git_clean_fd(segment):
    force = False
    directories = False
    for token in segment.split():
        if token == "--force":
            force = True
        if token in {"-d", "--directories"}:
            directories = True
        if token.startswith("-") and not token.startswith("--"):
            if "f" in token[1:]:
                force = True
            if "d" in token[1:]:
                directories = True
    return force and directories


def dangerous_database_command(command):
    if not dangerous_db_text(command):
        return False
    if re.search(r"\bpython(?:3(?:\.\d+)?)?\s+-c\b", command or ""):
        return True
    if re.search(r"(?:^|[^\w./-])mongo(?:sh)?\b", command or ""):
        return True
    return False


def shell_permission(command):
    if dangerous_rm(command) or dangerous_git(command) or dangerous_database_command(command):
        return "deny"
    return "allow"


def is_dotenv(path):
    return bool(path) and Path(path).name == ".env"


def read_permission(data):
    paths = [data.get("file_path") or ""]
    for attachment in data.get("attachments") or []:
        if isinstance(attachment, dict):
            paths.append(attachment.get("file_path") or "")
    if any(is_dotenv(path) for path in paths):
        return "deny"
    return "allow"


def mcp_permission(data):
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, str):
        tool_input = json.dumps(tool_input, default=str)
    text = f"{data.get('tool_name', '')} {tool_input}"
    if dangerous_db_text(text):
        return "deny"
    return "allow"


def deny_command():
    return {
        "permission": "deny",
        "user_message": DENY_TEXT,
        "agent_message": DENY_TEXT,
    }


def deny_read():
    return {"permission": "deny", "user_message": DENY_TEXT}


def allow():
    return {"permission": "allow"}


def decide(data):
    event = data.get("hook_event_name") or ""
    if event == "beforeReadFile" or (
        not event and "file_path" in data and "tool_name" not in data
    ):
        permission = read_permission(data)
        detail = data.get("file_path") or ""
        event_name = "beforeReadFile"
        denied = deny_read()
    elif event == "beforeMCPExecution" or (not event and "tool_name" in data):
        permission = mcp_permission(data)
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, str):
            tool_input = json.dumps(tool_input, default=str)
        detail = f"{data.get('tool_name', '')} {tool_input}"
        event_name = "beforeMCPExecution"
        denied = deny_command()
    else:
        permission = shell_permission(data.get("command") or "")
        detail = data.get("command") or ""
        event_name = event or "beforeShellExecution"
        denied = deny_command()

    decision = "DENY" if permission == "deny" else "ALLOW"
    log_event(decision, event_name, detail)
    if permission == "deny":
        return denied
    return allow()


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        log_event("DENY", "unparsed", "invalid hook input")
        sys.stdout.write(json.dumps(deny_command()))
        return 0
    if not isinstance(data, dict):
        log_event("DENY", "unparsed", "invalid hook input")
        sys.stdout.write(json.dumps(deny_command()))
        return 0
    sys.stdout.write(json.dumps(decide(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
