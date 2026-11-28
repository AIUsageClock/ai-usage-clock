import os
import subprocess
import sys
from pathlib import Path

from aiusageclock.webview import profile_cleanup


def test_processes_queueing_deletions_at_the_same_time_lose_none(tmp_path):
    """The app and its browser worker both add ids to pending-profile-delete.json."""
    src = str(Path(__file__).resolve().parents[1] / "src")
    code = (
        "import sys\n"
        "from aiusageclock.webview import profile_cleanup as pc\n"
        "pc._remove_tree = lambda *a, **k: OSError('locked')\n"
        "for i in range(25):\n"
        "    pc.delete_profile(f'{sys.argv[1]}-{i}', retries=1, delay_s=0)\n"
    )
    env = dict(os.environ)
    env.update(PYTHONPATH=src, APPDATA=str(tmp_path), LOCALAPPDATA=str(tmp_path),
               HOME=str(tmp_path), USERPROFILE=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path))
    processes = [
        subprocess.Popen([sys.executable, "-c", code, f"p{n}"], env=env) for n in range(4)
    ]
    for process in processes:
        assert process.wait(timeout=180) == 0

    queued = set(profile_cleanup.read_pending())
    expected = {f"p{n}-{i}" for n in range(4) for i in range(25)}
    assert expected - queued == set()


def test_the_pending_list_still_works_in_one_process(monkeypatch):
    monkeypatch.setattr(
        profile_cleanup, "_remove_tree", lambda *a, **k: OSError("locked")
    )
    assert profile_cleanup.delete_profile("a", retries=1, delay_s=0) is False
    assert profile_cleanup.delete_profile("b", retries=1, delay_s=0) is False
    assert profile_cleanup.read_pending() == ["a", "b"]

    monkeypatch.setattr(profile_cleanup, "_remove_tree", lambda *a, **k: None)
    assert profile_cleanup.process_pending() == ["a", "b"]
    assert profile_cleanup.read_pending() == []
