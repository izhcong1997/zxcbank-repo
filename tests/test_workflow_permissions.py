"""GITHUB_TOKEN must be limited in every Actions workflow.

Finding F-05: a workflow with no explicit permissions block receives the
repository default token, which can be broader than the job needs.
"""

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

_TOP_LEVEL_PERMISSIONS = re.compile(r"^permissions\s*:(.*)$")
_SCOPE = re.compile(
    r"^[ \t]+([A-Za-z0-9_-]+)[ \t]*:[ \t]*([^#\n]*?)[ \t]*(?:#.*)?$"
)


def top_level_permissions(text):
    """Return the workflow's top-level permissions, or None when unset.

    A scalar such as ``read-all`` is returned as a string. A mapping is
    returned as a dict of scope to access. Job-level blocks do not count:
    jobs that omit permissions would still inherit the default token.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line or line[0] in " \t#":
            continue
        match = _TOP_LEVEL_PERMISSIONS.match(line)
        if not match:
            continue
        inline = match.group(1).strip()
        if inline:
            return inline.split("#", 1)[0].strip()
        scopes = {}
        for follower in lines[index + 1 :]:
            if not follower.strip() or follower.lstrip().startswith("#"):
                continue
            if not follower[0].isspace():
                break
            scope = _SCOPE.match(follower)
            if scope is None:
                raise AssertionError(f"unparsed permissions line: {follower!r}")
            scopes[scope.group(1)] = scope.group(2).strip().strip("'\"")
        return scopes
    return None


def test_workflows_declare_top_level_permissions():
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, f"no workflows found in {WORKFLOWS}"
    missing = [
        path.name
        for path in files
        if top_level_permissions(path.read_text()) is None
    ]
    assert missing == [], (
        "workflows missing an explicit top-level permissions block: "
        + ", ".join(missing)
    )


def test_tests_workflow_token_is_contents_read():
    permissions = top_level_permissions((WORKFLOWS / "tests.yml").read_text())
    assert permissions == {"contents": "read"}


def test_missing_permissions_block_is_detected():
    workflow = "name: tests\n\non: push\n\njobs:\n  pytest:\n    runs-on: ubuntu-latest\n"
    assert top_level_permissions(workflow) is None
