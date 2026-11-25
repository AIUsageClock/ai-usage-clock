import json
import os
import subprocess
from unittest.mock import Mock
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aiusageclock.models import SnapshotStatus
from tests.agy_factory import make_fake_agy
from aiusageclock.providers import antigravity
from aiusageclock.providers.antigravity import (
    AntigravityProvider,
    _build_snapshot,
    _classify_bucket,
    _decode_output,
    _invoke_cli,
    resolve_cli,
)

FIXTURE = Path(__file__).parent / "fixtures" / "antigravity" / "quota_ok.json"
LATCH_ERROR = (
    "agy did not treat /quota as a built-in command; polling paused to avoid "
    "spending model quota. Update agy and restart AI Usage Clock."
)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _sync(provider: AntigravityProvider, monkeypatch) -> None:
    monkeypatch.setattr(provider, "_run_async", lambda work, on_done: on_done(work()))


def _refresh_with_payload(monkeypatch, payload: dict) -> AntigravityProvider:
    provider = AntigravityProvider()
    _sync(provider, monkeypatch)
    monkeypatch.setattr(antigravity, "resolve_cli", lambda _: "agy")
    monkeypatch.setattr(
        antigravity,
        "_invoke_cli",
        lambda _: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    return provider


def test_fixture_maps_metrics_in_group_and_window_order():
    snapshot = _build_snapshot(_payload())

    assert snapshot.status == SnapshotStatus.OK
    assert [metric.label for metric in snapshot.metrics] == [
        "Gemini 5h",
        "Gemini weekly",
        "Claude+GPT 5h",
        "Claude+GPT weekly",
        "Argon weekly",
    ]
    assert [metric.percent_used for metric in snapshot.metrics] == pytest.approx(
        [
            14.962172508239746,
            13.184946775436401,
            0.0,
            88.507279753684998,
            38.73084187507629,
        ]
    )
    assert [metric.window for metric in snapshot.metrics] == [
        timedelta(hours=5),
        timedelta(days=7),
        timedelta(hours=5),
        timedelta(days=7),
        timedelta(days=7),
    ]
    assert snapshot.metrics[2].resets_at is None
    assert snapshot.metrics[2].reset_label == "idle"
    assert all(
        metric.resets_at is not None for index, metric in enumerate(snapshot.metrics)
        if index != 2
    )
    assert snapshot.metrics[0].resets_at.tzinfo is None
    assert all(metric.tag is None for metric in snapshot.metrics)
    assert len(snapshot.raw["buckets"]) == 5


def test_bucket_without_description_is_parsed_and_integer_one_is_idle():
    payload = _payload()
    payload["command"]["data"]["groups"][1]["buckets"][1]["reset_time"] = (
        "2026-10-26T06:40:58Z"
    )
    snapshot = _build_snapshot(payload)
    metric = snapshot.metrics[2]

    assert metric.percent_used == 0
    assert metric.reset_label == "idle"
    assert metric.resets_at is None


@pytest.mark.parametrize(
    ("remaining", "expected_reset", "expected_label"),
    [
        (1, None, "idle"),
        (0.75, datetime(2026, 10, 26, 6, 40, 58), None),
    ],
)
def test_zero_usage_is_idle_but_used_limit_keeps_reset_time(
    remaining, expected_reset, expected_label
):
    payload = _payload()
    bucket = payload["command"]["data"]["groups"][1]["buckets"][1]
    bucket["remaining_fraction"] = remaining
    bucket["reset_time"] = "2026-10-26T06:40:58Z"

    metric = next(
        item
        for item in _build_snapshot(payload).metrics
        if item.label == "Claude+GPT 5h"
    )

    if expected_reset is None:
        assert metric.resets_at is None
    else:
        assert metric.resets_at == antigravity._parse_reset_at(
            bucket["reset_time"]
        )
    assert metric.reset_label == expected_label
    if remaining == 1:
        assert metric.note == "Countdown starts when you next use this limit."


def test_unknown_window_and_group_prefix_use_fallback_labels():
    payload = _payload()
    payload["command"]["data"]["groups"] = [
        {
            "name": "Other Provider",
            "buckets": [
                {
                    "id": "other-special",
                    "window": "quarterly",
                    "remaining_fraction": 0.5,
                    "reset_time": "not a date",
                }
            ],
        }
    ]

    metric = _build_snapshot(payload).metrics[0]

    assert metric.label == "Other Provider quarterly"
    assert metric.window is None
    assert metric.percent_used == 50
    assert metric.resets_at is None


def test_empty_groups_produce_ok_snapshot_without_metrics():
    payload = _payload()
    payload["command"]["data"]["groups"] = []

    snapshot = _build_snapshot(payload)

    assert snapshot.status == SnapshotStatus.OK
    assert snapshot.metrics == []


def test_decode_output_rejects_non_json_and_finds_final_json_line():
    with pytest.raises(ValueError, match="stdout is not JSON"):
        _decode_output("not JSON")

    assert _decode_output("diagnostic noise\n{\"status\": \"SUCCESS\"}\n") == {
        "status": "SUCCESS"
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda payload: payload.update(status="FAILED"), "agy error: FAILED"),
        (
            lambda payload: payload["command"].update(name="other"),
            "command.name is not usage",
        ),
        (
            lambda payload: payload["command"]["data"].update(groups={}),
            "command.data.groups is not a list",
        ),
    ],
)
def test_success_contract_rejections(change, message):
    payload = _payload()
    change(payload)

    with pytest.raises(ValueError, match=message):
        _build_snapshot(payload)


def test_prompt_fallback_latches_polling_without_second_cli_call(monkeypatch):
    payload = _payload()
    payload["num_turns"] = 1
    calls = []
    provider = _refresh_with_payload(monkeypatch, payload)

    def invoke(_):
        calls.append(1)
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    monkeypatch.setattr(antigravity, "_invoke_cli", invoke)
    first = []
    second = []

    provider.refresh(first.append)
    provider.refresh(second.append)

    assert len(calls) == 1
    assert first[0].status == second[0].status == SnapshotStatus.ERROR
    assert first[0].error == second[0].error == LATCH_ERROR


@pytest.mark.parametrize("field", ["num_turns", "total_tokens"])
def test_prompt_fallback_latches_for_turns_or_tokens(monkeypatch, field):
    payload = _payload()
    if field == "num_turns":
        payload["num_turns"] = 1
    else:
        payload["usage"]["total_tokens"] = 3
    provider = _refresh_with_payload(monkeypatch, payload)
    result = []

    provider.refresh(result.append)

    assert result[0].status == SnapshotStatus.ERROR
    assert result[0].error == LATCH_ERROR


def test_missing_executable_reports_error(monkeypatch):
    provider = AntigravityProvider()
    _sync(provider, monkeypatch)
    monkeypatch.setattr(antigravity, "resolve_cli", lambda _: None)
    result = []

    provider.refresh(result.append)

    assert result[0].status == SnapshotStatus.ERROR
    assert result[0].error == antigravity._NOT_FOUND_ERROR
    assert result[0].error.startswith("agy CLI not found")
    assert len(result[0].error) <= 200


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (FileNotFoundError("missing"), "failed to start agy: missing"),
        (subprocess.TimeoutExpired("agy", 60), "agy timed out"),
    ],
)
def test_cli_start_and_timeout_errors(monkeypatch, exception, expected):
    provider = AntigravityProvider()
    _sync(provider, monkeypatch)
    monkeypatch.setattr(antigravity, "resolve_cli", lambda _: "agy")

    def fail(_):
        raise exception

    monkeypatch.setattr(antigravity, "_invoke_cli", fail)
    result = []
    provider.refresh(result.append)

    assert result[0].status == SnapshotStatus.ERROR
    assert result[0].error == expected


@pytest.mark.parametrize(
    ("show_gemini", "show_third_party", "labels"),
    [
        (False, True, ["Claude+GPT 5h", "Claude+GPT weekly"]),
        (True, False, ["Gemini 5h", "Gemini weekly", "Argon weekly"]),
        (False, False, []),
    ],
)
def test_group_visibility_filters(show_gemini, show_third_party, labels):
    snapshot = _build_snapshot(
        _payload(),
        show_gemini=show_gemini,
        show_third_party=show_third_party,
    )

    assert [metric.label for metric in snapshot.metrics] == labels


def test_argon_group_before_gemini_group_keeps_distinct_labels():
    payload = _payload()
    groups = payload["command"]["data"]["groups"]
    payload["command"]["data"]["groups"] = [groups[2], groups[0], groups[1]]

    snapshot = _build_snapshot(payload)

    assert [metric.label for metric in snapshot.metrics] == [
        "Argon weekly",
        "Gemini 5h",
        "Gemini weekly",
        "Claude+GPT 5h",
        "Claude+GPT weekly",
    ]


def test_unknown_gemini_subfamily_uses_capitalized_segment_and_gemini_filter():
    payload = _payload()
    payload["command"]["data"]["groups"] = [
        {
            "name": "Gemini Experimental",
            "buckets": [
                {
                    "id": "gemini-foo-5h",
                    "window": "5h",
                    "remaining_fraction": 0.5,
                    "reset_time": "2026-10-28T06:20:10Z",
                }
            ],
        }
    ]

    shown = _build_snapshot(payload, show_gemini=True)
    hidden = _build_snapshot(payload, show_gemini=False)

    assert [metric.label for metric in shown.metrics] == ["Foo 5h"]
    assert hidden.metrics == []


@pytest.mark.parametrize(
    ("bucket_id", "group_name", "window_value", "expected"),
    [
        ("gemini-argon-wtu-weekly", "Gemini 4 Argon", "weekly", ("Argon", "gemini")),
        ("GEMINI-ARGON-WTU-WEEKLY", "Gemini 4 Argon", None, ("Argon", "gemini")),
        ("gemini-foo-5h", "Gemini Foo", None, ("Foo", "gemini")),
        ("gemini-weekly", "Gemini Models", None, ("Gemini", "gemini")),
        ("gemini-5h", "Gemini Models", None, ("Gemini", "gemini")),
        ("gemini-daily", "Gemini Models", "daily", ("Gemini", "gemini")),
        ("gemini--weekly", "Gemini Models", None, ("Gemini", "gemini")),
        ("gemini-", "Gemini Models", None, ("Gemini", "gemini")),
        ("gemini-weekly-x", "Gemini Models", None, ("Gemini", "gemini")),
        ("3p-weekly", "Claude and GPT models", None, ("Claude+GPT", "third_party")),
        ("3p-5h", "Claude and GPT models", None, ("Claude+GPT", "third_party")),
        ("other-special", "Other Provider", None, ("Other Provider", None)),
        ("", "Fallback Group", None, ("Fallback Group", None)),
    ],
)
def test_classify_bucket_branches(bucket_id, group_name, window_value, expected):
    assert _classify_bucket(bucket_id, group_name, window_value) == expected


def test_resolve_cli_prefers_explicit_path_then_which(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit-agy.exe"
    explicit.touch()
    discovered = tmp_path / "which-agy.exe"
    discovered.touch()
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: str(discovered))

    assert resolve_cli(str(explicit)) == str(explicit)
    assert resolve_cli(None) == str(discovered)


def test_resolve_cli_uses_local_app_data_fallback_on_windows(monkeypatch, tmp_path):
    fallback = tmp_path / "agy" / "bin" / "agy.exe"
    fallback.parent.mkdir(parents=True)
    fallback.touch()
    monkeypatch.setattr(antigravity.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: None)

    assert resolve_cli(None) == str(fallback)


def test_invoke_cli_arguments_and_isolated_working_directory(monkeypatch):
    captured = {}
    monkeypatch.delenv("AGY_CLI_DISABLE_AUTO_UPDATE", raising=False)
    monkeypatch.setenv("AI_USAGE_CLOCK_TEST_ENV", "preserved")

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        assert Path(kwargs["cwd"]).is_dir()
        assert list(Path(kwargs["cwd"]).iterdir()) == []
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(antigravity.subprocess, "run", fake_run)

    assert "AGY_CLI_DISABLE_AUTO_UPDATE" not in antigravity.os.environ
    _invoke_cli("agy-executable")

    assert captured["args"] == [
        "agy-executable",
        "--print",
        "/quota",
        "--output-format",
        "json",
        "--mode",
        "plan",
        "--sandbox",
        "--print-timeout",
        "30s",
    ]
    assert "shell" not in captured
    assert captured["stdin"] == subprocess.DEVNULL
    assert captured["timeout"] == 60
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert captured["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert captured["env"]["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
    assert captured["env"]["AI_USAGE_CLOCK_TEST_ENV"] == "preserved"
    assert "AGY_CLI_DISABLE_AUTO_UPDATE" not in antigravity.os.environ


import json
import subprocess
from types import SimpleNamespace
from aiusageclock.app import App
from aiusageclock.config import Config
from aiusageclock.providers.antigravity import normalize_cli_path

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  C:/tools/agy.exe  ", "C:/tools/agy.exe"),
        ('"C:/tools/agy.exe"', "C:/tools/agy.exe"),
        ("'C:/tools/agy.exe'", "C:/tools/agy.exe"),
        ("   ", None),
        ("", None),
    ],
)
def test_normalize_cli_path_trims_and_unquotes(value, expected):
    assert normalize_cli_path(value) == expected

def test_normalize_cli_path_expands_home_and_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("AGY_BIN", str(tmp_path / "agy.exe"))
    assert Path(normalize_cli_path("~/bin/agy.exe")) == tmp_path / "bin" / "agy.exe"
    assert normalize_cli_path("$AGY_BIN") == str(tmp_path / "agy.exe")
    if os.name == "nt":
        assert normalize_cli_path("%AGY_BIN%") == str(tmp_path / "agy.exe")

def test_provider_uses_explicit_existing_file_without_autodetect(monkeypatch, tmp_path):
    executable = make_fake_agy(tmp_path / "agy.exe")
    provider = AntigravityProvider(cli_path=f' "{executable}" ')
    _sync(provider, monkeypatch)
    which = lambda _: pytest.fail("explicit path must not trigger PATH lookup")
    monkeypatch.setattr(antigravity.shutil, "which", which)
    calls = []
    monkeypatch.setattr(
        antigravity,
        "_invoke_cli",
        lambda path: calls.append(path)
        or subprocess.CompletedProcess([], 0, json.dumps({
            "status": "SUCCESS", "num_turns": 0, "usage": {"total_tokens": 0},
            "command": {"name": "usage", "data": {"groups": []}},
        }), ""),
    )
    result = []
    provider.refresh(result.append)
    assert calls == [str(executable)]
    assert result[0].status is SnapshotStatus.OK

def test_provider_reports_missing_explicit_file_without_autodetect(
    monkeypatch, tmp_path
):
    missing = tmp_path / "missing agy.exe"
    provider = AntigravityProvider(cli_path=f' "{missing}" ')
    _sync(provider, monkeypatch)
    monkeypatch.setattr(
        antigravity.shutil, "which",
        lambda _: pytest.fail("invalid explicit path must not autodetect"),
    )
    result = []
    provider.refresh(result.append)
    assert result[0].status is SnapshotStatus.ERROR
    assert result[0].error == f"agy CLI not found at {missing}"

def test_none_keeps_path_then_windows_fallback_order(monkeypatch, tmp_path):
    path_cli = tmp_path / "path-agy.exe"
    fallback = tmp_path / "agy" / "bin" / "agy.exe"
    fallback.parent.mkdir(parents=True)
    fallback.touch()
    monkeypatch.setattr(antigravity.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: str(path_cli))
    assert resolve_cli(None) == str(path_cli)
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: None)
    assert resolve_cli(None) == str(fallback)

def _provider_for_payload(monkeypatch, tmp_path, payload):
    cli = make_fake_agy(tmp_path / "agy.exe")
    provider = AntigravityProvider(cli_path=str(cli))
    _sync(provider, monkeypatch)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr(antigravity.subprocess, "run", run)
    return provider, calls

def test_offline_eligibility_error_does_not_latch(monkeypatch, tmp_path):
    payload = {
        "conversation_id": "test",
        "duration_seconds": 0.1,
        "error": (
            'Eligibility check failed: Post "https://googleapis.com/": '
            "proxyconnect tcp: dial tcp 127.0.0.1:9: connectex: No connection"
        ),
        "num_turns": 0,
        "response": "",
        "status": "ERROR",
        "usage": {"total_tokens": 0},
    }
    provider, calls = _provider_for_payload(monkeypatch, tmp_path, payload)
    snapshots = []

    provider.refresh(snapshots.append)
    provider.refresh(snapshots.append)

    assert len(calls) == 2
    assert snapshots[0].status is SnapshotStatus.ERROR
    assert snapshots[0].error.startswith("agy error:")
    assert provider._latched_error is None

@pytest.mark.parametrize("usage_change", [{"num_turns": 1}, {"total_tokens": 1}])
def test_token_usage_latches_and_stops_future_calls(monkeypatch, tmp_path, usage_change):
    payload = {
        "status": "SUCCESS",
        "num_turns": 0,
        "usage": {"total_tokens": 0},
        "command": {"name": "usage", "data": {"groups": []}},
    }
    payload.update({k: v for k, v in usage_change.items() if k == "num_turns"})
    if "total_tokens" in usage_change:
        payload["usage"]["total_tokens"] = usage_change["total_tokens"]
    provider, calls = _provider_for_payload(monkeypatch, tmp_path, payload)
    snapshots = []

    provider.refresh(snapshots.append)
    provider.refresh(snapshots.append)

    assert len(calls) == 1
    assert snapshots[0].error == snapshots[1].error
    assert provider._latched_error

def test_indeterminate_usage_latches(monkeypatch, tmp_path):
    provider, calls = _provider_for_payload(
        monkeypatch, tmp_path, {"status": "ERROR", "error": "unknown"}
    )
    snapshots = []

    provider.refresh(snapshots.append)
    provider.refresh(snapshots.append)

    assert len(calls) == 1
    assert provider._latched_error

def test_success_without_command_and_zero_tokens_does_not_latch(monkeypatch, tmp_path):
    payload = {
        "status": "SUCCESS",
        "num_turns": 0,
        "usage": {"total_tokens": 0},
    }
    provider, calls = _provider_for_payload(monkeypatch, tmp_path, payload)
    snapshots = []

    provider.refresh(snapshots.append)
    provider.refresh(snapshots.append)

    assert len(calls) == 2
    assert all(s.status is SnapshotStatus.ERROR for s in snapshots)
    assert snapshots[0].error == "unexpected agy output: command is missing"
    assert provider._latched_error is None

def test_wrong_explicit_executable_is_rejected_without_running(monkeypatch, tmp_path):
    executable = tmp_path / "notepad.exe"
    executable.touch()
    provider = AntigravityProvider(cli_path=str(executable))
    _sync(provider, monkeypatch)
    monkeypatch.setattr(
        antigravity.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    snapshots = []

    provider.refresh(snapshots.append)

    assert snapshots[0].error.startswith("Not the agy CLI:")
    assert snapshots[0].raw["config_error"] is True

def test_missing_explicit_path_is_configuration_error(monkeypatch, tmp_path):
    missing = tmp_path / "agy.exe"
    provider = AntigravityProvider(cli_path=str(missing))
    _sync(provider, monkeypatch)
    snapshots = []

    provider.refresh(snapshots.append)

    assert snapshots[0].error.startswith("agy CLI not found at")
    assert snapshots[0].raw["config_error"] is True

def test_existing_agy_executable_is_invoked(monkeypatch, tmp_path):
    payload = {
        "status": "SUCCESS",
        "num_turns": 0,
        "usage": {"total_tokens": 0},
        "command": {"name": "usage", "data": {"groups": []}},
    }
    provider, calls = _provider_for_payload(monkeypatch, tmp_path, payload)
    snapshots = []

    provider.refresh(snapshots.append)

    assert len(calls) == 1
    assert snapshots[0].status is SnapshotStatus.OK

def _provider_app(config):
    app = App.__new__(App)
    app._config = config
    app._providers = {}
    app._snapshots = {}
    app._widget = SimpleNamespace(
        _tiles={}, ensure_tile=lambda name, label: app._widget._tiles.setdefault(name, label),
        remove_tile=lambda name: app._widget._tiles.pop(name, None),
    )
    app._sync_usage_cache = lambda: None
    return app

def test_antigravity_latch_survives_provider_rebuild_disable_and_reenable(monkeypatch):
    config = Config()
    config.providers.claude = config.providers.codex = False
    config.providers.copilot = config.providers.openrouter = False
    config.providers.antigravity = True
    app = _provider_app(config)
    calls = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps({
        "status": "SUCCESS", "num_turns": 1,
        "usage": {"total_tokens": 1},
    }), ""))
    monkeypatch.setattr(antigravity, "_invoke_cli", calls)
    monkeypatch.setattr(antigravity, "resolve_cli", lambda _: "agy")
    monkeypatch.setattr(AntigravityProvider, "_run_async", lambda self, work, done: done(work()))
    app._build_providers()
    app._providers["antigravity"].refresh(lambda snapshot: None)
    assert antigravity._PROCESS_LATCHED_ERROR
    app._build_providers()
    app._providers["antigravity"].refresh(lambda snapshot: None)
    assert calls.call_count == 1
    config.providers.antigravity = False
    app._build_providers()
    config.providers.antigravity = True
    app._build_providers()
    snapshots = []
    app._providers["antigravity"].refresh(snapshots.append)
    assert calls.call_count == 1
    assert snapshots[0].error == antigravity._PROCESS_LATCHED_ERROR


# ---------------------------------------------------------------------------
# agy 1.5.x adaptation (AG-1 .. AG-12)
# ---------------------------------------------------------------------------

FIXTURE_1_5_13 = (
    Path(__file__).parent / "fixtures" / "antigravity" / "quota_1_5_13.json"
)
HISTORY_LABELS = [
    "Gemini 5h",
    "Gemini weekly",
    "Claude+GPT 5h",
    "Claude+GPT weekly",
    "Argon weekly",
]


def _payload_1_5_13() -> dict:
    return json.loads(FIXTURE_1_5_13.read_text(encoding="utf-8"))


def _exit_result(returncode: int, stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _refresh_twice(monkeypatch, result) -> tuple[list, list]:
    """Refresh a provider twice against a canned CLI result; return (snaps, calls)."""
    provider = AntigravityProvider()
    _sync(provider, monkeypatch)
    calls = []
    monkeypatch.setattr(antigravity, "resolve_cli", lambda _: "agy")
    monkeypatch.setattr(
        antigravity, "_invoke_cli", lambda exe: calls.append(exe) or result
    )
    snapshots = []
    provider.refresh(snapshots.append)
    provider.refresh(snapshots.append)
    return snapshots, calls


# --- AG-4: agy 1.5.13 fixture ----------------------------------------------


def test_quota_1_5_13_fixture_pins_the_five_history_labels():
    payload = _payload_1_5_13()
    assert payload["status"] == "SUCCESS"
    assert payload["num_turns"] == 0
    assert payload["usage"]["total_tokens"] == 0
    assert payload["command"]["name"] == "usage"
    buckets = [
        b["id"]
        for group in payload["command"]["data"]["groups"]
        for b in group["buckets"]
    ]
    assert sorted(buckets) == sorted(
        ["gemini-5h", "gemini-weekly", "3p-5h", "3p-weekly",
         "gemini-argon-wtu-weekly"]
    )

    snapshot = _build_snapshot(payload)

    assert snapshot.status == SnapshotStatus.OK
    assert [m.label for m in snapshot.metrics] == HISTORY_LABELS
    assert all(m.percent_used == 0 for m in snapshot.metrics)
    assert all(m.resets_at is None for m in snapshot.metrics)
    assert all(m.reset_label == "idle" for m in snapshot.metrics[:4])


@pytest.mark.parametrize(
    ("show_gemini", "show_third_party", "labels"),
    [
        (False, True, ["Claude+GPT 5h", "Claude+GPT weekly"]),
        (True, False, ["Gemini 5h", "Gemini weekly", "Argon weekly"]),
    ],
)
def test_quota_1_5_13_family_toggles(show_gemini, show_third_party, labels):
    snapshot = _build_snapshot(
        _payload_1_5_13(),
        show_gemini=show_gemini,
        show_third_party=show_third_party,
    )

    assert [m.label for m in snapshot.metrics] == labels


# --- AG-11: tray short codes pinned from real parsed labels ----------------


def test_quota_1_5_13_labels_map_to_tray_codes():
    from aiusageclock.widget import tray_metric_code

    labels = [m.label for m in _build_snapshot(_payload_1_5_13()).metrics]

    assert [tray_metric_code(label) for label in labels] == [
        "G5", "GW", "C5", "CW", "AW",
    ]


# --- AG-1: exit code 2 (GEMINI_API_KEY) -----------------------------------


@pytest.mark.parametrize(
    "stdout",
    ["", "not json at all", json.dumps({"status": "ERROR", "error": "x"})],
)
def test_exit_code_2_is_recoverable_and_does_not_latch(monkeypatch, stdout):
    from aiusageclock.widget import _short_error_reason

    snapshots, calls = _refresh_twice(monkeypatch, _exit_result(2, stdout))

    assert len(calls) == 2
    assert all(s.status is SnapshotStatus.ERROR for s in snapshots)
    assert antigravity._PROCESS_LATCHED_ERROR is None
    error = snapshots[0].error
    assert len(error) <= 200
    assert "exit code 2" in error
    assert "Google account" in error
    assert _short_error_reason(error) == "signed out"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "ERROR", "num_turns": 1, "usage": {"total_tokens": 0}},
        {"status": "ERROR", "num_turns": 0, "usage": {"total_tokens": 7}},
    ],
)
def test_exit_code_2_with_spent_tokens_still_latches(monkeypatch, payload):
    snapshots, calls = _refresh_twice(
        monkeypatch, _exit_result(2, json.dumps(payload))
    )

    assert len(calls) == 1
    assert antigravity._PROCESS_LATCHED_ERROR
    assert snapshots[0].error == snapshots[1].error == LATCH_ERROR


# --- AG-12: print-timeout exit code 3 --------------------------------------


def test_exit_code_3_print_timeout_without_tokens_is_a_timeout(monkeypatch):
    from aiusageclock.widget import _short_error_reason

    payload = {
        "status": "ERROR",
        "finished_reason": "print_timeout",
        "num_turns": 0,
        "usage": {"total_tokens": 0},
    }
    snapshots, calls = _refresh_twice(
        monkeypatch, _exit_result(3, json.dumps(payload))
    )

    assert len(calls) == 2
    assert antigravity._PROCESS_LATCHED_ERROR is None
    assert snapshots[0].error == antigravity._PRINT_TIMEOUT_ERROR
    assert _short_error_reason(snapshots[0].error) == "timeout"


def test_exit_code_3_print_timeout_with_tokens_still_latches(monkeypatch):
    payload = {
        "status": "ERROR",
        "finished_reason": "print_timeout",
        "num_turns": 1,
        "usage": {"total_tokens": 12},
    }
    snapshots, calls = _refresh_twice(
        monkeypatch, _exit_result(3, json.dumps(payload))
    )

    assert len(calls) == 1
    assert snapshots[0].error == LATCH_ERROR


def test_exit_code_3_without_print_timeout_keeps_existing_handling(monkeypatch):
    # Unrecognised output still goes through the normal parser, which latches
    # an indeterminate payload exactly as before.
    snapshots, calls = _refresh_twice(
        monkeypatch, _exit_result(3, json.dumps({"status": "ERROR"}))
    )

    assert len(calls) == 1
    assert snapshots[0].error == LATCH_ERROR


# --- AG-2: ~/.local/bin/agy fallback on macOS and Linux --------------------


def _install_local_bin_agy(tmp_path: Path, mode: int = 0o755) -> Path:
    candidate = tmp_path / ".local" / "bin" / "agy"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate.chmod(mode)
    return candidate


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_resolve_cli_uses_local_bin_fallback_on_macos_and_linux(
    monkeypatch, tmp_path, platform
):
    candidate = _install_local_bin_agy(tmp_path)
    monkeypatch.setattr(antigravity.sys, "platform", platform)
    monkeypatch.setattr(antigravity.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: None)
    # chmod is a no-op on Windows checkouts of this suite; pin the permission
    # check so the test is deterministic on every OS.
    monkeypatch.setattr(antigravity.os, "access", lambda path, mode: True)

    assert resolve_cli(None) == str(candidate)


def test_resolve_cli_prefers_which_over_local_bin(monkeypatch, tmp_path):
    _install_local_bin_agy(tmp_path)
    monkeypatch.setattr(antigravity.sys, "platform", "linux")
    monkeypatch.setattr(antigravity.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: "/usr/bin/agy")

    assert resolve_cli(None) == "/usr/bin/agy"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_resolve_cli_local_bin_missing_or_not_executable_returns_none(
    monkeypatch, tmp_path, platform
):
    monkeypatch.setattr(antigravity.sys, "platform", platform)
    monkeypatch.setattr(antigravity.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: None)
    assert resolve_cli(None) is None  # file does not exist

    _install_local_bin_agy(tmp_path, mode=0o644)
    monkeypatch.setattr(antigravity.os, "access", lambda path, mode: False)
    assert resolve_cli(None) is None  # exists but no execute permission


def test_resolve_cli_win32_does_not_use_local_bin_fallback(monkeypatch, tmp_path):
    _install_local_bin_agy(tmp_path)
    monkeypatch.setattr(antigravity.sys, "platform", "win32")
    monkeypatch.setattr(antigravity.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    monkeypatch.setattr(antigravity.shutil, "which", lambda _: None)

    assert resolve_cli(None) is None


# --- AG-3: not-found guidance ----------------------------------------------


def test_not_found_error_has_path_guidance_and_keeps_short_label():
    from aiusageclock.widget import _short_error_reason

    error = antigravity._NOT_FOUND_ERROR

    assert error.startswith("agy CLI not found")
    assert "which agy" in error
    assert len(error) <= 200
    assert _short_error_reason(error) == "agy not found"
    lowered = error.lower()
    for keyword in ("timeout", "timed out", "connectex", "dial tcp"):
        assert keyword not in lowered


# --- AG-10: executable permission for a manually chosen path ---------------


def _manual_provider(monkeypatch, tmp_path, platform, executable):
    cli = tmp_path / "agy"
    cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(antigravity.sys, "platform", platform)
    monkeypatch.setattr(antigravity.os, "access", lambda path, mode: executable)
    provider = AntigravityProvider(cli_path=str(cli))
    _sync(provider, monkeypatch)
    return provider, cli


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_manual_path_without_execute_permission_is_config_error(
    monkeypatch, tmp_path, platform
):
    provider, cli = _manual_provider(monkeypatch, tmp_path, platform, False)
    monkeypatch.setattr(
        antigravity.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    snapshots = []

    provider.refresh(snapshots.append)

    assert snapshots[0].status is SnapshotStatus.ERROR
    assert snapshots[0].error == f"agy CLI is not executable: {cli}"
    assert snapshots[0].raw["config_error"] is True


def test_manual_path_with_execute_permission_runs(monkeypatch, tmp_path):
    provider, cli = _manual_provider(monkeypatch, tmp_path, "linux", True)
    calls = []
    monkeypatch.setattr(
        antigravity, "_invoke_cli",
        lambda exe: calls.append(exe) or _exit_result(0, json.dumps(_payload_1_5_13())),
    )
    snapshots = []

    provider.refresh(snapshots.append)

    assert calls == [str(cli)]
    assert snapshots[0].status is SnapshotStatus.OK


def test_windows_ignores_execute_permission_for_manual_path(monkeypatch, tmp_path):
    provider, cli = _manual_provider(monkeypatch, tmp_path, "win32", False)
    calls = []
    monkeypatch.setattr(
        antigravity, "_invoke_cli",
        lambda exe: calls.append(exe) or _exit_result(0, json.dumps(_payload_1_5_13())),
    )
    snapshots = []

    provider.refresh(snapshots.append)

    assert calls == [str(cli)]
    assert snapshots[0].status is SnapshotStatus.OK


# --- AG-9: group description -----------------------------------------------


def test_group_descriptions_are_stored_on_metrics_without_touching_labels():
    snapshot = _build_snapshot(_payload_1_5_13())
    by_label = {m.label: m.group_description for m in snapshot.metrics}

    assert by_label["Gemini 5h"] == by_label["Gemini weekly"]
    assert by_label["Gemini 5h"].startswith("Models within this group: Gemini 4")
    assert by_label["Claude+GPT 5h"] == by_label["Claude+GPT weekly"]
    assert "Claude Opus 5.5" in by_label["Claude+GPT 5h"]
    assert by_label["Argon weekly"].startswith("For paid Pro plans")
    assert [m.label for m in snapshot.metrics] == HISTORY_LABELS


def test_missing_empty_or_non_string_description_is_ignored():
    for value in (None, "", "   ", 5, ["x"], {"a": 1}):
        payload = _payload_1_5_13()
        payload["command"]["data"]["groups"][0]["description"] = value
        snapshot = _build_snapshot(payload)
        assert snapshot.metrics[0].label == "Gemini 5h"
        assert snapshot.metrics[0].group_description is None
        assert snapshot.metrics[2].group_description  # other groups unaffected

    payload = _payload_1_5_13()
    del payload["command"]["data"]["groups"][0]["description"]
    assert _build_snapshot(payload).metrics[0].group_description is None


def test_description_is_plain_text_and_capped_at_200_chars():
    payload = _payload_1_5_13()
    payload["command"]["data"]["groups"][0]["description"] = (
        "<b>Models</b>\n  within   this group: " + "x" * 400
    )
    description = _build_snapshot(payload).metrics[0].group_description

    assert len(description) == 200
    assert "<" not in description and ">" not in description
    assert "\n" not in description and "  " not in description
    # Only the angle brackets are dropped; the remaining text is kept.
    assert description.startswith("b Models /b within this group: xxx")


def test_group_description_does_not_reach_history_key_or_usage_cache(
    monkeypatch, tmp_path
):
    from aiusageclock import usage_cache

    snapshot = _build_snapshot(_payload_1_5_13())
    monkeypatch.setattr(usage_cache, "usage_cache_path", lambda: tmp_path / "c.json")

    usage_cache.write_usage_cache({"antigravity": snapshot})
    written = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    metrics = written["accounts"]["antigravity"]["metrics"]

    assert [m["label"] for m in metrics] == HISTORY_LABELS
    assert "description" not in json.dumps(written).lower()
    assert usage_cache.CACHE_SCHEMA_VERSION == 1


def test_tile_row_and_compact_group_tooltips_show_group_members(qtbot):
    from aiusageclock.config import Config
    from aiusageclock.widget import UsageWidget

    snapshot = _build_snapshot(_payload_1_5_13())
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(snapshot, "Antigravity")
    tile = widget._tiles["antigravity"]

    row_tips = [row.toolTip() for row in tile._rows]
    assert "Models within this group" in row_tips[0]
    assert "Claude Opus 5.5" in row_tips[2]
    assert "Countdown starts when you next use this limit." in row_tips[0]

    tile.expand_btn.click()
    group_tips = [
        row.layout().itemAt(0).widget().toolTip() for row in tile._compact_group_rows
    ]
    assert "Gemini 4 Neon" in group_tips[0].replace("\n", " ")
    assert group_tips[2].replace("\n", " ").startswith("For paid Pro plans")


def test_tile_tooltip_is_unchanged_when_description_is_absent(qtbot):
    from aiusageclock.config import Config
    from aiusageclock.widget import UsageWidget

    payload = _payload_1_5_13()
    for group in payload["command"]["data"]["groups"]:
        del group["description"]
    widget = UsageWidget(Config())
    qtbot.addWidget(widget)
    widget.update_snapshot(_build_snapshot(payload), "Antigravity")
    tile = widget._tiles["antigravity"]

    assert tile._rows[0].toolTip() == "Countdown starts when you next use this limit."

# --- agy 1.5.14: Argon folded into the shared Gemini group ------------------

FIXTURE_1_5_14 = (
    Path(__file__).parent / "fixtures" / "antigravity" / "quota_1_5_14.json"
)
LABELS_1_5_14 = ["Gemini 5h", "Gemini weekly", "Claude+GPT 5h", "Claude+GPT weekly"]


def _payload_1_5_14() -> dict:
    return json.loads(FIXTURE_1_5_14.read_text(encoding="utf-8"))


def test_quota_1_5_14_fixture_pins_the_four_history_labels():
    snapshot = _build_snapshot(_payload_1_5_14())

    assert snapshot.status == SnapshotStatus.OK
    assert [m.label for m in snapshot.metrics] == LABELS_1_5_14
    assert all(m.percent_used == 0 for m in snapshot.metrics)
    assert all(m.resets_at is None for m in snapshot.metrics)
    assert all(m.reset_label == "idle" for m in snapshot.metrics)


def test_quota_1_5_14_gemini_rows_carry_the_group_description():
    by_label = {m.label: m.group_description for m in _build_snapshot(_payload_1_5_14()).metrics}

    assert "Carbon" in by_label["Gemini 5h"]
    assert by_label["Gemini 5h"] == by_label["Gemini weekly"]
    assert "Claude Opus 5.5" in by_label["Claude+GPT weekly"]


@pytest.mark.parametrize(
    ("show_gemini", "show_third_party", "labels"),
    [
        (True, True, LABELS_1_5_14),
        (False, True, ["Claude+GPT 5h", "Claude+GPT weekly"]),
        (True, False, ["Gemini 5h", "Gemini weekly"]),
    ],
)
def test_quota_1_5_14_family_toggles(show_gemini, show_third_party, labels):
    snapshot = _build_snapshot(
        _payload_1_5_14(),
        show_gemini=show_gemini,
        show_third_party=show_third_party,
    )

    assert [m.label for m in snapshot.metrics] == labels


def test_epoch_reset_time_on_a_used_bucket_is_treated_as_unknown():
    # agy 1.5.14 reports 1970-01-01T00:00:00Z for the Claude+GPT group even
    # though the quota is in use; that must never surface as a 1970 reset.
    payload = _payload_1_5_14()
    for bucket in payload["command"]["data"]["groups"][1]["buckets"]:
        bucket["remaining_fraction"] = 0.6
    snapshot = _build_snapshot(payload)
    third_party = [m for m in snapshot.metrics if m.label.startswith("Claude+GPT")]

    assert len(third_party) == 2
    for metric in third_party:
        assert metric.percent_used == pytest.approx(40.0)
        assert metric.resets_at is None


@pytest.mark.parametrize(
    "value", ["1970-01-01T00:00:00Z", "1969-12-31T00:00:00Z", "1970-01-01T00:00:00"]
)
def test_parse_reset_at_treats_epoch_and_earlier_as_unknown(value):
    assert antigravity._parse_reset_at(value) is None
    assert antigravity._parse_reset_at("2099-01-01T00:00:00Z") is not None


# --- helper check: fake agy files are launchable on POSIX -------------------


def test_make_fake_agy_requests_execute_bits(monkeypatch, tmp_path):
    """Runs on every OS: the helper must chmod 0o755 (what POSIX needs)."""
    from tests import agy_factory

    calls = []
    real_chmod = os.chmod
    monkeypatch.setattr(
        agy_factory.os, "chmod",
        lambda path, mode: (calls.append((Path(path), mode)), real_chmod(path, mode))[1],
    )
    cli = make_fake_agy(tmp_path / "agy")
    assert cli.is_file()
    assert calls == [(cli, 0o755)]


@pytest.mark.skipif(os.name == "nt", reason="Windows has no POSIX execute bits")
def test_make_fake_agy_passes_real_access_check(monkeypatch, tmp_path):
    plain = tmp_path / "plain-agy"
    plain.touch()
    monkeypatch.setattr(antigravity.sys, "platform", "linux")
    assert antigravity.cli_is_executable(str(plain)) is False
    assert antigravity.cli_is_executable(str(make_fake_agy(tmp_path / "agy"))) is True
