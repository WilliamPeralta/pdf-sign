import json
import subprocess
import sys


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "pdf_sign", *args], capture_output=True, text=True
    )


def test_help_lists_subcommands():
    r = run("--help")
    assert r.returncode == 0
    assert "detect" in r.stdout and "\n    sign" in r.stdout


def test_missing_file_is_json_error_exit_1(tmp_path):
    r = run("detect", str(tmp_path / "nope.pdf"))
    assert r.returncode == 1
    assert r.stdout == ""
    assert json.loads(r.stderr)["error"]["code"] == "file_not_found"


def test_invalid_pdf_is_exit_3(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")
    r = run("detect", str(bad))
    assert r.returncode == 3
    assert json.loads(r.stderr)["error"]["code"] == "invalid_pdf"


def test_usage_error_is_json_exit_1():
    r = run("detect")
    assert r.returncode == 1
    assert json.loads(r.stderr)["error"]["code"] == "usage"


def test_sign_subcommand_has_help():
    r = run("sign", "--help")
    assert r.returncode == 0
    assert "--signature" in r.stdout
