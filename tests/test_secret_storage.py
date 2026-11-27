import sys

import pytest

from aiusageclock.secret_storage import load_secret, save_secret


@pytest.fixture(autouse=True)
def _allow_plaintext_on_non_windows(monkeypatch):
    """Production refuses to write secrets on non-Windows; tests opt in explicitly."""
    if sys.platform != "win32":
        monkeypatch.setenv("AIUSAGECLOCK_ALLOW_PLAINTEXT_SECRETS", "1")


def test_round_trip_short():
    save_secret("test-short", "hello")
    assert load_secret("test-short") == "hello"


def test_round_trip_large():
    """The whole point of this module: handle values >2.5KB that keyring can't."""
    big = "x" * 20_000  # 20KB — comfortably exceeds Credential Manager's limit
    save_secret("test-large", big)
    assert load_secret("test-large") == big


def test_overwrite():
    save_secret("test-overwrite", "first")
    save_secret("test-overwrite", "second")
    assert load_secret("test-overwrite") == "second"


def test_delete():
    save_secret("test-delete", "value")
    save_secret("test-delete", None)
    assert load_secret("test-delete") is None


def test_load_missing_returns_none():
    assert load_secret("never-set-this-key") is None


def test_multiple_secrets_independent():
    save_secret("a", "alpha")
    save_secret("b", "beta")
    assert load_secret("a") == "alpha"
    assert load_secret("b") == "beta"
    save_secret("a", None)
    assert load_secret("a") is None
    assert load_secret("b") == "beta"


# ----- two processes (the app and its browser worker) share this file -----


def test_concurrent_writers_in_separate_processes_lose_nothing(monkeypatch):
    import os
    import subprocess
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[1] / "src")
    code = (
        "import sys\n"
        "from aiusageclock.secret_storage import save_secret\n"
        "for i in range(12):\n"
        "    save_secret(f'{sys.argv[1]}-{i}', 'value-' + 'x' * 200)\n"
    )
    env = dict(os.environ, PYTHONPATH=src, AIUSAGECLOCK_ALLOW_PLAINTEXT_SECRETS="1")
    processes = [
        subprocess.Popen([sys.executable, "-c", code, f"p{n}"], env=env) for n in range(4)
    ]
    for process in processes:
        assert process.wait(timeout=120) == 0

    for n in range(4):
        for i in range(12):
            assert load_secret(f"p{n}-{i}") is not None, f"p{n}-{i} was lost"


def test_a_write_replaces_the_file_in_one_step_and_leaves_no_temporary_file():
    from aiusageclock import secret_storage

    save_secret("one", "1")
    save_secret("two", "2")

    folder = secret_storage._secrets_path().parent  # noqa: SLF001
    assert sorted(path.name for path in folder.glob("secrets.dat*") if path.suffix == ".tmp") == []
    assert load_secret("one") == "1"


def test_the_lock_is_not_used_where_secrets_are_never_written(monkeypatch):
    from aiusageclock import secret_storage

    monkeypatch.setattr(secret_storage.sys, "platform", "linux")
    monkeypatch.delenv("AIUSAGECLOCK_ALLOW_PLAINTEXT_SECRETS", raising=False)

    with secret_storage._file_lock():  # noqa: SLF001
        pass

    assert not secret_storage._secrets_path().with_name("secrets.dat.lock").exists()  # noqa: SLF001