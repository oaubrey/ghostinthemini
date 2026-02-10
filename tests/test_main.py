"""Tests for main entry point."""

from unittest.mock import patch

import pytest

from ghostinthemini.main import ghost_pulse_check, main


def test_main_runs_without_error(capsys: pytest.CaptureFixture[str]) -> None:
    """main() runs and prints something."""
    main()
    out, _ = capsys.readouterr()
    assert "Boo" in out


def test_ghost_pulse_check_success(capsys: pytest.CaptureFixture[str]) -> None:
    """ghost_pulse_check prints success when Ollama responds."""
    fake_response = {
        "message": {
            "content": "Yes, I am online and running.",
        }
    }

    with patch("ghostinthemini.main.ollama.chat", return_value=fake_response):
        ghost_pulse_check()

    out, _ = capsys.readouterr()
    assert "Initializing pulse check" in out
    assert "Yes, I am online and running." in out
    assert "Connection Successful" in out


def test_ghost_pulse_check_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """ghost_pulse_check prints an error when Ollama is unreachable."""
    with patch(
        "ghostinthemini.main.ollama.chat",
        side_effect=ConnectionError("Connection refused"),
    ):
        ghost_pulse_check()

    out, _ = capsys.readouterr()
    assert "Error" in out
    assert "Make sure Ollama is running" in out
