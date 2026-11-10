"""最小 CLI。"""

from __future__ import annotations

import subprocess
import sys

import pytest

from jpcalc.cli import main


def test_module_help_runs():
    r = subprocess.run([sys.executable, "-m", "jpcalc", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "check-config" in r.stdout and "guard" in r.stdout


def test_check_config_ok(capsys):
    assert main(["check-config"]) == 0
    out = capsys.readouterr().out
    assert "config: OK" in out and "JA_DOC_CALC_DB" in out


def test_guard_ok():
    assert main(["guard"]) == 0


def test_command_required():
    with pytest.raises(SystemExit):
        main([])
