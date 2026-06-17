# SPDX-License-Identifier: Apache-2.0
"""Background service management: arg forwarding, pidfile, liveness, status (M9)."""

import argparse
import os

import infermesh.cli as cli


def _ns(**kw) -> argparse.Namespace:
    base = dict(model_dir=None, host=None, port=None, backend=None,
                max_concurrent_requests=None, idle_timeout=None,
                max_process_memory=None, api_key=None, providers=None,
                sse_keepalive=None, pin=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_serve_argv_roundtrips_flags():
    argv = cli._serve_argv(_ns(model_dir="/m", port=8021, backend="mock",
                               providers="/p.json", sse_keepalive=5.0, pin=["a", "b"]))
    assert "--model-dir" in argv and "/m" in argv
    assert "--port" in argv and "8021" in argv
    assert "--backend" in argv and "mock" in argv
    assert "--providers" in argv and "/p.json" in argv
    assert "--sse-keepalive" in argv and "5.0" in argv
    assert argv.count("--pin") == 2 and "a" in argv and "b" in argv
    assert "--api-key" not in argv          # None-valued flags are omitted


def test_pidfile_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PID_PATH", tmp_path / "infermesh.pid")
    assert cli._read_pidfile() is None
    cli._write_pidfile({"pid": 1234, "host": "127.0.0.1", "port": 8021})
    info = cli._read_pidfile()
    assert info["pid"] == 1234 and info["port"] == 8021
    cli._remove_pidfile()
    assert cli._read_pidfile() is None


def test_pid_alive():
    assert cli._pid_alive(os.getpid()) is True
    assert cli._pid_alive(2_000_000_000) is False   # implausibly high pid
    assert cli._pid_alive(None) is False
    assert cli._pid_alive(0) is False


def test_status_not_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PID_PATH", tmp_path / "nope.pid")
    assert cli.cmd_status(_ns()) == 1
    assert "not running" in capsys.readouterr().out
