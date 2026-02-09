"""Tests for main entry point."""

import pytest

from ghostinthemini.main import main


def test_main_runs_without_error(capsys: pytest.CaptureFixture[str]) -> None:
    """main() runs and prints something."""
    main()
    out, _ = capsys.readouterr()
    assert "Boo" in out or "👻" in out
