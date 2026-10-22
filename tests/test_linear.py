import json
import logging
import re

import pytest
import requests
import responses

from aiusageclock.config import Config
from aiusageclock.models import SnapshotStatus
from aiusageclock.providers.linear import (
    LINEAR_API,
    LinearProvider,
    _build_snapshot,
    _extract_issue_count,
    _is_auth_error,
)

SECRET = "lin_api_SECRETKEY123"

AUTH_ERRORS = [
    {
        "message": "Authentication required, not authenticated",
        "extensions": {"type": "authentication error", "code": "AUTHENTICATION_ERROR"},
    }
]


def _data(counts=(100, 23), subscription=None) -> dict:
    return {
        "organization": {"subscription": subscription},
        "teams": {"nodes": [{"issueCount": count} for count in counts]},
    }


def _run(monkeypatch, *, key=SECRET, config=None):
    monkeypatch.setattr("aiusageclock.providers.linear.get_linear_key", lambda: key)
    monkeypatch.setattr(
        LinearProvider,
        "_run_async",
        lambda self, work, on_done: on_done(work()),
    )
    provider = LinearProvider(config or Config())
    captured = []
    provider.refresh(captured.append)
    assert len(captured) == 1
    return captured[0]


# --- _build_snapshot -------------------------------------------------------


def test_free_plan_reports_issue_percentage():
    snapshot = _build_snapshot(_data((100, 23)), issue_limit=250)

    assert snapshot.provider == "linear"
    assert snapshot.status == SnapshotStatus.OK
    (metric,) = snapshot.metrics
    assert metric.label == "Issues"
    assert metric.percent_used == pytest.approx(49.2)
    assert metric.reset_label == "123 / 250"
    assert metric.window is None
    assert metric.resets_at is None
    assert "Free plan" in (metric.note or "")


@pytest.mark.parametrize(
    ("counts", "expected"), [((250,), 100.0), ((200, 60), 104.0)]
)
def test_free_plan_at_and_over_limit_is_not_clamped(counts, expected):
    (metric,) = _build_snapshot(_data(counts), issue_limit=250).metrics

    assert metric.percent_used == pytest.approx(expected)


def test_paid_plan_has_no_gauge():
    snapshot = _build_snapshot(
        _data(subscription={"type": "standard"}), issue_limit=250
    )

    (metric,) = snapshot.metrics
    assert metric.percent_used is None
    assert metric.reset_label == "no limit"
    assert "Paid plan" in (metric.note or "")


def test_custom_issue_limit_recomputes():
    (metric,) = _build_snapshot(_data((100, 23)), issue_limit=500).metrics

    assert metric.percent_used == pytest.approx(24.6)
    assert metric.reset_label == "123 / 500"


def test_snapshot_does_not_embed_payload():
    assert _build_snapshot(_data(), issue_limit=250).raw == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"organization": {"subscription": None}},  # teams missing
        {"organization": {"subscription": None}, "teams": {}},
        {"organization": {"subscription": None}, "teams": {"nodes": "x"}},
        {"teams": {"nodes": []}},  # organization missing
        {"organization": None, "teams": {"nodes": []}},
        {"organization": {}, "teams": {"nodes": []}},  # subscription missing
        {"organization": {"subscription": "pro"}, "teams": {"nodes": []}},
    ],
)
def test_build_snapshot_rejects_malformed_payload(payload):
    with pytest.raises(ValueError):
        _build_snapshot(payload, issue_limit=250)


@pytest.mark.parametrize("bad", [None, "5", True, False, -1, 1.5])
def test_extract_issue_count_rejects_bad_values(bad):
    node = {"issueCount": bad}
    with pytest.raises(ValueError):
        _extract_issue_count({"teams": {"nodes": [node]}})
    node.pop("issueCount")
    with pytest.raises(ValueError):
        _extract_issue_count({"teams": {"nodes": [node]}})


def test_extract_issue_count_sums_teams_and_handles_none():
    assert _extract_issue_count(_data((1, 2, 3))) == 6
    assert _extract_issue_count(_data(())) == 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"extensions": {"code": "AUTHENTICATION_ERROR"}}, True),
        ({"extensions": {"code": "authentication_error"}}, True),
        ({"extensions": {"type": "Authentication Error"}}, True),
        ({"extensions": {"code": "INVALID_INPUT"}}, False),
        ({"extensions": {"code": 5, "type": 7}}, False),
        ({"extensions": "AUTHENTICATION_ERROR"}, False),
        ({"message": "x"}, False),
        ("AUTHENTICATION_ERROR", False),
        (None, False),
        (["authentication"], False),
    ],
)
def test_is_auth_error(error, expected):
    assert _is_auth_error(error) is expected


# --- refresh: key handling -------------------------------------------------


@responses.activate
@pytest.mark.parametrize("key", [None, "", "   "])
def test_refresh_without_key_requests_setup_and_sends_nothing(monkeypatch, key):
    snapshot = _run(monkeypatch, key=key)

    assert snapshot.provider == "linear"
    assert snapshot.status == SnapshotStatus.AUTH_REQUIRED
    assert "API key" in (snapshot.error or "")
    assert len(responses.calls) == 0


# --- refresh: success and request shape -----------------------------------


@responses.activate
def test_refresh_sends_expected_request_and_returns_usage(monkeypatch):
    responses.add(responses.POST, LINEAR_API, json={"data": _data()}, status=200)

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.OK
    request = responses.calls[0].request
    assert request.method == "POST"
    assert request.url == LINEAR_API
    assert request.headers["Authorization"] == SECRET
    assert not request.headers["Authorization"].startswith("Bearer")
    query = json.loads(request.body)["query"]
    assert "issueCount" in query
    assert "subscription" in query
    # Only the fields the provider reads are requested.
    for unused in ("createdIssueCount", "urlKey", "name", "key"):
        assert not re.search(r"(?<!\w)" + unused + r"(?!\w)", query), unused


@responses.activate
def test_refresh_reads_issue_limit_from_config(monkeypatch):
    responses.add(responses.POST, LINEAR_API, json={"data": _data()}, status=200)
    config = Config()
    config.linear.issue_limit = 500

    snapshot = _run(monkeypatch, config=config)

    (metric,) = snapshot.metrics
    assert metric.percent_used == pytest.approx(24.6)
    assert metric.reset_label == "123 / 500"


@responses.activate
def test_refresh_reports_paid_plan(monkeypatch):
    responses.add(
        responses.POST,
        LINEAR_API,
        json={"data": _data(subscription={"type": "standard"})},
        status=200,
    )

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.OK
    assert snapshot.metrics[0].percent_used is None


# --- refresh: error classification ----------------------------------------


@responses.activate
def test_http_401_requires_auth(monkeypatch):
    responses.add(responses.POST, LINEAR_API, status=401)

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.AUTH_REQUIRED
    assert "rejected" in (snapshot.error or "")


@responses.activate
def test_http_401_with_non_auth_json_body_still_requires_auth(monkeypatch):
    responses.add(
        responses.POST,
        LINEAR_API,
        json={"errors": [{"message": "nope"}]},
        status=401,
    )

    assert _run(monkeypatch).status == SnapshotStatus.AUTH_REQUIRED


@responses.activate
@pytest.mark.parametrize("status", [200, 400])
def test_graphql_authentication_error_requires_auth(monkeypatch, status):
    responses.add(
        responses.POST, LINEAR_API, json={"errors": AUTH_ERRORS}, status=status
    )

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.AUTH_REQUIRED
    assert "rejected" in (snapshot.error or "")


@responses.activate
def test_graphql_other_error_is_error_and_truncated(monkeypatch):
    responses.add(
        responses.POST,
        LINEAR_API,
        json={
            "errors": [
                {"message": "x" * 500, "extensions": {"code": "INVALID_INPUT"}}
            ]
        },
        status=200,
    )

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.ERROR
    assert (snapshot.error or "").startswith("Linear API error: ")
    assert len(snapshot.error or "") <= 200


@responses.activate
def test_graphql_error_with_non_string_message_uses_generic_text(monkeypatch):
    responses.add(
        responses.POST,
        LINEAR_API,
        json={"errors": [{"message": {"a": 1}}]},
        status=200,
    )

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.ERROR
    assert snapshot.error == "Linear API error."


@responses.activate
@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (400, "RATELIMITED", "Rate limit exceeded"),
        (403, "FORBIDDEN", "Forbidden: insufficient scope"),
    ],
)
def test_non_2xx_graphql_errors_keep_the_server_reason(
    monkeypatch, status, code, message
):
    responses.add(
        responses.POST,
        LINEAR_API,
        json={"errors": [{"message": message, "extensions": {"code": code}}]},
        status=status,
    )

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.ERROR
    assert message in (snapshot.error or "")
    assert f"HTTP {status}" in (snapshot.error or "")
    assert len(snapshot.error or "") <= 200


@responses.activate
def test_non_2xx_graphql_error_with_non_string_message_mentions_status(monkeypatch):
    responses.add(
        responses.POST,
        LINEAR_API,
        json={"errors": [{"message": {"a": 1}}]},
        status=400,
    )

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.ERROR
    assert snapshot.error == "Linear API error (HTTP 400)."


@responses.activate
def test_non_2xx_graphql_error_is_truncated(monkeypatch):
    responses.add(
        responses.POST,
        LINEAR_API,
        json={"errors": [{"message": "x" * 500}]},
        status=500,
    )

    snapshot = _run(monkeypatch)

    assert (snapshot.error or "").startswith("Linear API error (HTTP 500): ")
    assert len(snapshot.error or "") <= 200


@responses.activate
def test_non_2xx_without_json_body_reports_only_the_status(monkeypatch):
    responses.add(responses.POST, LINEAR_API, status=500)

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.ERROR
    assert snapshot.error == "Linear API returned HTTP 500."


@responses.activate
@pytest.mark.parametrize("status", [500, 429])
def test_other_http_statuses_are_errors(monkeypatch, status):
    responses.add(responses.POST, LINEAR_API, status=status)

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.ERROR
    assert str(status) in (snapshot.error or "")


@responses.activate
def test_connection_error_is_error(monkeypatch):
    responses.add(
        responses.POST, LINEAR_API, body=requests.ConnectionError("offline")
    )

    snapshot = _run(monkeypatch)

    assert snapshot.status == SnapshotStatus.ERROR
    assert "ConnectionError" in (snapshot.error or "")


@responses.activate
def test_timeout_is_error(monkeypatch):
    responses.add(responses.POST, LINEAR_API, body=requests.Timeout("slow"))

    assert _run(monkeypatch).status == SnapshotStatus.ERROR


@responses.activate
@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": "<html>not json</html>"},
        {"json": ["not", "a", "dict"]},
        {"json": {}},
        {"json": {"data": None}},
        {"json": {"data": "x"}},
    ],
)
def test_unexpected_bodies_are_errors(monkeypatch, kwargs):
    responses.add(responses.POST, LINEAR_API, status=200, **kwargs)

    assert _run(monkeypatch).status == SnapshotStatus.ERROR


def _mutate(data, fn):
    fn(data)
    return data


@responses.activate
@pytest.mark.parametrize(
    "data",
    [
        _mutate(_data(), lambda d: d["teams"]["nodes"][0].pop("issueCount")),
        _mutate(_data(), lambda d: d["teams"]["nodes"][0].update(issueCount="5")),
        _mutate(_data(), lambda d: d["teams"]["nodes"][0].update(issueCount=True)),
        _mutate(_data(), lambda d: d["teams"]["nodes"][0].update(issueCount=-1)),
        _mutate(_data(), lambda d: d.pop("teams")),
        _mutate(_data(), lambda d: d.pop("organization")),
    ],
)
def test_malformed_fields_are_errors(monkeypatch, data):
    responses.add(responses.POST, LINEAR_API, json={"data": data}, status=200)

    assert _run(monkeypatch).status == SnapshotStatus.ERROR


# --- secrecy ---------------------------------------------------------------


def _register_failure(case):
    if case == "401":
        responses.add(responses.POST, LINEAR_API, status=401)
    elif case == "500":
        responses.add(responses.POST, LINEAR_API, status=500)
    elif case == "auth_errors":
        responses.add(responses.POST, LINEAR_API, json={"errors": AUTH_ERRORS})
    elif case == "errors":
        responses.add(
            responses.POST,
            LINEAR_API,
            json={"errors": [{"message": "boom", "extensions": {"code": "X"}}]},
        )
    elif case == "connection":
        responses.add(
            responses.POST, LINEAR_API, body=requests.ConnectionError("offline")
        )
    elif case == "bad_count":
        bad = _data()
        bad["teams"]["nodes"][0]["issueCount"] = "5"
        responses.add(responses.POST, LINEAR_API, json={"data": bad})


@responses.activate
@pytest.mark.parametrize(
    "case", ["401", "500", "auth_errors", "errors", "connection", "bad_count"]
)
def test_api_key_never_appears_in_logs_or_errors(monkeypatch, caplog, case):
    _register_failure(case)
    caplog.set_level(logging.DEBUG)

    snapshot = _run(monkeypatch)

    assert snapshot.status != SnapshotStatus.OK
    assert SECRET not in (snapshot.error or "")
    assert SECRET not in caplog.text
    assert all(SECRET not in record.getMessage() for record in caplog.records)


@responses.activate
def test_non_ascii_key_requires_auth_without_sending_or_leaking(monkeypatch, caplog):
    bad_key = "lin_api_abc…中"
    caplog.set_level(logging.DEBUG)

    snapshot = _run(monkeypatch, key=bad_key)

    assert snapshot.status == SnapshotStatus.AUTH_REQUIRED
    assert len(responses.calls) == 0
    error = snapshot.error or ""
    assert "latin-1" not in error
    assert "…" not in error
    assert "中" not in error
    assert bad_key not in caplog.text
    assert "中" not in caplog.text
    assert "…" not in caplog.text
    assert "latin-1" not in caplog.text


def test_fetch_rejects_non_ascii_key_before_any_request():
    from aiusageclock.providers.linear import _LinearAuthError, _fetch

    with pytest.raises(_LinearAuthError):
        _fetch("lin_api_abc中")


@responses.activate
@pytest.mark.parametrize(
    "bad_key",
    ["lin_api_abc\ndef", "lin_api_abc def", "lin_api_abc\tdef"],
)
def test_key_with_control_or_space_characters_requires_auth_without_sending(
    monkeypatch, bad_key
):
    snapshot = _run(monkeypatch, key=bad_key)

    assert snapshot.status == SnapshotStatus.AUTH_REQUIRED
    assert "invalid characters" in (snapshot.error or "")
    assert len(responses.calls) == 0
