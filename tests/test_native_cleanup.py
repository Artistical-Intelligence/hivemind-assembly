from types import SimpleNamespace
import pytest
from hivemind_assembly.core import native_process


@pytest.mark.parametrize(
    "code,locks,success",
    [
        (32, 2, True),
        (33, 2, True),
        (5, 2, True),
        (32, 99, False),
        (5, 99, False),
        (13, 1, False),
    ],
)
def test_windows_file_cleanup_is_bounded_and_does_not_hide_errors(
    monkeypatch, code, locks, success
):
    class Directory:
        name = "fixture"
        attempts = 0

        def cleanup(self):
            self.attempts += 1
            if self.attempts <= locks:
                error = PermissionError("fixture file lock")
                error.winerror = code
                raise error

    directory = Directory()
    clock = iter(range(20))
    monkeypatch.setattr(native_process, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        native_process,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock) / 2, sleep=lambda _: None),
    )
    monkeypatch.setattr(
        native_process.tempfile, "TemporaryDirectory", lambda **_: directory
    )
    if success:
        with native_process.process_directory() as path:
            assert path == "fixture"
        assert directory.attempts == locks + 1
    else:
        with pytest.raises(PermissionError, match="fixture file lock"):
            with native_process.process_directory():
                pass
        assert directory.attempts == (4 if code in (5, 32, 33) else 1)


@pytest.mark.skipif(
    native_process.os.name != "nt",
    reason="Repeated Windows file-lock regression requires Windows",
)
def test_windows_repeated_process_cleanup(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    original = native_process.tempfile.TemporaryDirectory
    directories = []

    def temporary(**kwargs):
        directory = original(**kwargs)
        directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(native_process.tempfile, "TemporaryDirectory", temporary)
    for _ in range(5):
        result = native_process.run(
            [sys.executable, "-c", "import time;time.sleep(20)"], tmp_path, timeout=0.2
        )
        assert result["status"] == "timeout"
        result = native_process.run(
            [sys.executable, "-c", 'print("X"*20000)'], tmp_path, output_limit=1024
        )
        assert result["status"] == "output_limit"
        assert not any(path.exists() for path in directories)
