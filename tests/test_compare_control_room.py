import importlib.util
import json

_spec = importlib.util.spec_from_file_location(
    "compare_control_room",
    "monitoring-db/compare_control_room.py",
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
changed = _module.changed
post_alert = _module.post_alert
summarize = _module.summarize


def room(**overrides):
    data = {
        "generated_at": "2026-10-26T15:00:00Z",
        "steps": [{"id": 1, "name": "Code pushed"}],
        "releases": [
            {
                "number": 141,
                "title": "Transfer note search",
                "created_at": "2026-10-26T14:00:00Z",
                "steps": [
                    {"id": 4, "status": "blocked", "detail": "Blocked", "at": "2026-10-26T14:10:00Z"}
                ],
            }
        ],
        "attention": [{"release": 141, "reason": "Blocked", "at": "2026-10-26T14:10:00Z"}],
        "production": {
            "version": "v1.1",
            "deployed_at": "2026-10-26T14:05:00Z",
            "incidents": [
                {
                    "number": 413,
                    "title": "INC-0413",
                    "labels": ["incident", "sev1"],
                    "opened_at": "2026-10-26T14:12:00Z",
                }
            ],
        },
    }
    data.update(overrides)
    return data


def test_timestamp_only_changes_are_ignored():
    old = room()
    new = room()
    new["generated_at"] = "2026-10-26T16:00:00Z"
    new["production"]["deployed_at"] = "2026-10-26T16:00:00Z"
    new["production"]["incidents"][0]["opened_at"] = "2026-10-26T16:00:00Z"
    new["releases"][0]["steps"][0]["at"] = "2026-10-26T16:00:00Z"
    new["attention"][0]["at"] = "2026-10-26T16:00:00Z"
    assert changed(old, new) is False


def test_summary_names_the_real_changes():
    old = room()
    new = room()
    new["production"]["version"] = "v1.0"
    new["production"]["deployed_at"] = "2026-10-26T18:00:00Z"
    new["production"]["incidents"] = []
    new["releases"][0]["steps"][0]["status"] = "done"
    new["releases"][0]["steps"][0]["at"] = "2026-10-26T18:00:00Z"
    new["attention"] = []
    assert changed(old, new) is True
    text = summarize(old, new)
    assert "Production v1.1 -> v1.0" in text
    assert "Incident #413 closed" in text
    assert "Release #141 step 4 is done" in text
    assert "Needs attention is 0" in text
    assert "\n" not in text


def test_post_skips_empty_secrets_and_hides_the_key(capsys):
    calls = []
    assert post_alert("", "", "Production nothing -> v1.1", opener=lambda *_a, **_k: calls.append(1)) == 0
    assert calls == []
    assert "Skipping POST" in capsys.readouterr().out

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def opener(request, timeout=20):
        calls.append(request.get_header("Authorization"))
        calls.append(json.loads(request.data.decode()))
        return Response()

    assert post_alert("https://captain.example/hook", "super-secret-key", "Incident #413 opened", opener=opener) == 0
    captured = capsys.readouterr().out
    assert calls[0] == "Bearer super-secret-key"
    assert calls[1] == {"reason": "control room changed", "summary": "Incident #413 opened"}
    assert "super-secret-key" not in captured
    assert "captain.example" not in captured
