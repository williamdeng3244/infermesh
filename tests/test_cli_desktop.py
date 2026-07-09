# SPDX-License-Identifier: Apache-2.0
"""App-like launch: `--no-open` on start/restart + the Linux desktop launcher."""

from pathlib import Path

from infermesh import cli


def test_start_and_restart_accept_no_open():
    p = cli.build_parser()
    assert p.parse_args(["start", "--no-open"]).no_open is True
    assert p.parse_args(["restart", "--no-open"]).no_open is True
    assert p.parse_args(["start"]).no_open is False


def test_no_open_not_forwarded_to_child_serve():
    p = cli.build_parser()
    args = p.parse_args(["start", "--no-open", "--port", "8123"])
    assert "--no-open" not in cli._serve_argv(args)


def test_desktop_install_writes_launcher(tmp_path):
    rc = cli.main(["desktop-install", "--apps-dir", str(tmp_path)])
    assert rc == 0
    text = (tmp_path / "infermesh.desktop").read_text()
    assert "[Desktop Entry]" in text
    exec_line = text.split("Exec=", 1)[1].splitlines()[0]
    assert "start" in exec_line              # double-click = start + auto-open
    icon = Path(text.split("Icon=", 1)[1].splitlines()[0])
    assert icon.exists() and icon.suffix == ".svg"   # packaged asset, ships in the wheel
