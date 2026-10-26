import json

from ops.incident_flow import (
    INCIDENT_TITLE,
    METRIC,
    deploy,
    deploy_message,
    health_message,
    lookup,
    page,
    reject_message,
    resolve,
)

WHEN = "26 Oct 2026, 23:15 SGT"


class Response:
    def __init__(self, status, payload):
        self.status = status
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Router:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.bodies = []

    def __call__(self, req, timeout=30):
        path = req.full_url.split("/repos/izhcong1997/zxcbank-repo", 1)[1]
        self.calls.append((req.method, path))
        self.bodies.append(None if req.data is None else json.loads(req.data.decode()))
        key = (req.method, path.split("?", 1)[0])
        if key not in self.routes:
            return Response(404, {"message": f"no route {req.method} {path}"})
        status, payload = self.routes[key]
        if callable(payload):
            payload = payload(req)
        return Response(status, payload)


def github(routes):
    from ops.incident_flow import GitHub

    router = Router(routes)
    return GitHub("izhcong1997/zxcbank-repo", "test-token", opener=router), router


def outputs_of(func, gh):
    found = {}
    func(gh, lambda name, value: found.__setitem__(name, value))
    return found


def test_lookup_with_nothing_deployed(capsys):
    gh, router = github({("GET", "/deployments"): (200, [])})
    assert lookup(gh, lambda *_args: None) == 0
    assert capsys.readouterr().out.strip() == "Nothing deployed yet"
    assert router.calls == [("GET", "/deployments?environment=production&per_page=20")]


def test_lookup_finds_current_success_and_previous_inactive():
    gh, _router = github(
        {
            ("GET", "/deployments"): (
                200,
                [{"id": 2, "ref": "v1.1"}, {"id": 1, "ref": "v1.0"}],
            ),
            ("GET", "/deployments/2/statuses"): (200, [{"state": "success"}]),
            ("GET", "/deployments/1/statuses"): (
                200,
                [{"state": "inactive"}, {"state": "success"}],
            ),
        }
    )
    found = outputs_of(lookup, gh)
    assert found == {"deployed": "true", "version": "v1.1", "previous": "v1.0"}


def test_deploy_ignores_other_people_and_other_comments():
    gh, router = github({})
    event = {
        "issue": {"number": 7, "labels": [{"name": "incident"}]},
        "comment": {"body": "/deploy v1.0", "user": {"login": "someone"}},
    }
    assert deploy(gh, "issue_comment", event, "", WHEN) == 0
    event["comment"]["user"]["login"] = "izhcong1997"
    event["comment"]["body"] = "please deploy"
    assert deploy(gh, "issue_comment", event, "", WHEN) == 0
    event["issue"]["labels"] = []
    event["comment"]["body"] = "/deploy v1.0"
    assert deploy(gh, "issue_comment", event, "", WHEN) == 0
    assert router.calls == []


def test_deploy_rejects_a_missing_tag_on_the_issue(capsys):
    gh, router = github(
        {
            ("GET", "/git/ref/tags/v9.9"): (404, {"message": "Not Found"}),
            ("POST", "/issues/7/comments"): (201, {}),
        }
    )
    event = {
        "issue": {"number": 7, "labels": [{"name": "incident"}]},
        "comment": {"body": "/deploy v9.9\n", "user": {"login": "izhcong1997"}},
    }
    assert deploy(gh, "issue_comment", event, "", WHEN) == 1
    assert reject_message("v9.9") in capsys.readouterr().out
    assert ("POST", "/deployments") not in router.calls
    assert router.bodies[-1] == {"body": reject_message("v9.9")}
    assert ("POST", "/issues/7/comments") in router.calls


def test_deploy_rejects_a_version_that_is_not_a_tag_name(capsys):
    gh, router = github({("GET", "/issues"): (200, [])})
    assert deploy(gh, "workflow_dispatch", None, "v1.1; curl", WHEN) == 1
    assert "Rejected v1.1; curl" in capsys.readouterr().out
    assert all(";" not in path for _method, path in router.calls)
    assert ("POST", "/deployments") not in router.calls


def test_deploy_marks_an_existing_tag_successful(capsys):
    gh, router = github(
        {
            ("GET", "/issues"): (200, []),
            ("GET", "/git/ref/tags/v1.1"): (200, {"ref": "refs/tags/v1.1"}),
            ("POST", "/deployments"): (201, {"id": 9}),
            ("POST", "/deployments/9/statuses"): (201, {"state": "success"}),
        }
    )
    assert deploy(gh, "workflow_dispatch", None, "v1.1", WHEN) == 0
    assert deploy_message("v1.1", "26 Oct 2026, 23:15 SGT") in capsys.readouterr().out
    assert router.bodies[2]["ref"] == "v1.1"
    assert router.bodies[2]["environment"] == "production"
    assert router.bodies[2]["required_contexts"] == []
    assert router.bodies[3] == {
        "state": "success",
        "environment": "production",
        "description": "Deployed v1.1",
        "auto_inactive": True,
    }


def test_resolve_comments_and_closes_the_incident(capsys):
    gh, router = github(
        {
            ("GET", "/issues"): (200, [{"number": 7, "title": INCIDENT_TITLE}]),
            ("POST", "/issues/7/comments"): (201, {}),
            ("PATCH", "/issues/7"): (200, {"state": "closed"}),
        }
    )
    assert resolve(gh, "v1.0") == 0
    assert router.bodies[1] == {"body": health_message("v1.0")}
    assert router.bodies[2] == {"state": "closed"}
    assert "Closed #7" in capsys.readouterr().out


def test_page_opens_one_incident_and_skips_an_empty_secret(capsys):
    gh, router = github(
        {
            ("GET", "/issues"): (200, []),
            ("GET", "/labels/incident"): (404, {}),
            ("POST", "/labels"): (201, {}),
            ("GET", "/labels/sev1"): (200, {}),
            ("POST", "/issues"): (201, {"number": 41}),
        }
    )
    posts = []
    assert (
        page(
            gh,
            "v1.1",
            "v1.0",
            "https://github.com/izhcong1997/zxcbank-repo/actions/runs/5",
            WHEN,
            "",
            "",
            opener=lambda *_args, **_kwargs: posts.append("sent"),
        )
        == 0
    )
    captured = capsys.readouterr().out
    assert "Skipping POST because GROK_INCIDENT_URL or GROK_INCIDENT_KEY is empty" in captured
    assert posts == []
    issue = router.bodies[-1]
    assert issue["title"] == INCIDENT_TITLE
    assert issue["labels"] == ["incident", "sev1"]
    assert f"Metric: {METRIC}" in issue["body"]
    assert "Deployed version: v1.1" in issue["body"]
    assert "Previous good version: v1.0" in issue["body"]


def test_page_does_not_open_a_second_incident_or_post():
    gh, router = github(
        {("GET", "/issues"): (200, [{"number": 41, "title": INCIDENT_TITLE}])}
    )
    posts = []
    assert (
        page(gh, "v1.1", "v1.0", "https://example.run", WHEN, "https://hooks.example", "secret", opener=lambda *_a, **_k: posts.append(1))
        == 0
    )
    assert router.calls == [("GET", "/issues?state=open&labels=incident&per_page=20")]
    assert posts == []


def test_page_posts_the_alert_without_printing_the_key(capsys):
    gh, _router = github(
        {
            ("GET", "/issues"): (200, []),
            ("GET", "/labels/incident"): (200, {}),
            ("GET", "/labels/sev1"): (200, {}),
            ("POST", "/issues"): (201, {"number": 41}),
        }
    )
    seen = {}

    def opener(req, timeout=20):
        seen["header"] = req.get_header("Authorization")
        seen["body"] = json.loads(req.data.decode())
        return Response(202, {})

    page(
        gh,
        "v1.1",
        "v1.0",
        "https://github.com/izhcong1997/zxcbank-repo/actions/runs/5",
        WHEN,
        "https://hooks.example/incident",
        "super-secret-key",
        opener=opener,
    )
    assert seen["header"] == "Bearer super-secret-key"
    assert seen["body"]["incident_number"] == "INC-0413"
    assert seen["body"]["service"] == "payments-api"
    assert seen["body"]["severity"] == "sev1"
    assert seen["body"]["deployed_version"] == "v1.1"
    assert seen["body"]["previous_good_version"] == "v1.0"
    assert "super-secret-key" not in capsys.readouterr().out
    assert "https://hooks.example/incident" not in capsys.readouterr().out


def test_workflows_match_the_demo_rules():
    deploy_file = open(".github/workflows/deploy.yml", encoding="utf-8").read()
    health_file = open(".github/workflows/health-check.yml", encoding="utf-8").read()
    pager_file = open(".github/workflows/zxc-pager.yml", encoding="utf-8").read()
    assert "workflow_dispatch:" in deploy_file
    assert "issue_comment:" in deploy_file
    assert "deployments: write" in deploy_file
    assert "issues: write" in deploy_file
    assert "contents: read" in deploy_file
    assert "git commit" not in deploy_file
    assert "git push" not in deploy_file
    assert "# schedule:" in health_file
    assert 'cron: "*/10 * * * *"' in health_file
    assert "\nschedule:" not in health_file
    assert "zxc-pager.yml" in health_file
    assert "persist-credentials: false" in health_file
    assert "GROK_INCIDENT_URL" in pager_file
    assert "GROK_INCIDENT_KEY" in pager_file
    assert "git commit" not in health_file + pager_file


def test_ownership_matches_real_files():
    text = open("ops/ownership.yml", encoding="utf-8").read()
    assert "templates/index.html" in text
    assert "transfers" not in text
    assert "lending-oncall@zxcbank.example" in text
    assert "care-oncall@zxcbank.example" in text
    assert "izhcong1997.sean@gmail.com" in text
