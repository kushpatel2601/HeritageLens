from __future__ import annotations

import signal
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakeserver import BASE, TOKEN, FakeServer

from heritage_gpu import cli, runner
from heritage_gpu.client import ApiClient


@pytest.fixture(autouse=True)
def _restore_sigterm() -> Iterator[None]:
    previous = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, previous)


def _patch_client(
    monkeypatch: pytest.MonkeyPatch, module: Any, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    def factory(base_url: str, token: str, **kw: Any) -> ApiClient:
        http = httpx.Client(transport=httpx.MockTransport(handler))
        return ApiClient(base_url, token, http=http, retries=0, sleep=lambda _s: None)

    monkeypatch.setattr(module, "ApiClient", factory)


def test_config_from_flags_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERITAGE_TOKEN", "from-env")
    monkeypatch.setenv("HERITAGE_NAME", "env-name")
    args = cli.build_parser().parse_args(
        [
            "run",
            "--api-url",
            "https://t.example",
            "--name",
            "flag-name",
            "--types",
            "ocr, caption",
            "--fake",
            "--max-jobs",
            "3",
            "--idle-exit",
            "5",
            "--work-dir",
            "scratch",
            "--translator",
            "nllb",
        ]
    )
    cfg = cli.config_from_args(args)
    assert cfg.base_url == "https://t.example/api/v1" and cfg.token == "from-env" and cfg.name == "flag-name"
    assert cfg.job_types == ("ocr", "caption") and cfg.fake is True and cfg.translator == "nllb"
    assert cfg.max_jobs == 3 and cfg.idle_exit_seconds == 5.0 and cfg.work_dir == Path("scratch")


def test_fake_flag_is_tri_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERITAGE_FAKE", "1")
    assert cli.config_from_args(cli.build_parser().parse_args(["selftest"])).fake is True  # env not overridden


def test_usage_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    with pytest.raises(SystemExit) as exit_:
        cli.main(["run", "--types", "ocr,summarise"])
    assert exit_.value.code == 2 and "unknown job types" in capsys.readouterr().err


def test_selftest_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["selftest", "--fake", "--log-level", "WARNING"]) == 0
    assert capsys.readouterr().out.count("ok   ") == 4


def _ops_handler(server: FakeServer, status: str = "ok") -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ready"):
            body = {"status": status, "version": "0.1.0", "database": "sqlite", "workers_online": {"cpu": 1}}
            return httpx.Response(200 if status == "ok" else 503, json=body)
        if request.url.path.endswith("/stats"):
            return httpx.Response(200, json={"queue_depth": {"gpu": 3}})
        return server.handle(request)

    return handler


@pytest.mark.parametrize(
    ("token", "status", "code", "expected"),
    [
        (TOKEN, "ok", 0, "token    : accepted"),
        ("wrong", "ok", 1, "REJECTED"),
        (TOKEN, "degraded", 1, "status   : degraded"),
    ],
)
def test_check_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    token: str,
    status: str,
    code: int,
    expected: str,
) -> None:
    _patch_client(monkeypatch, cli, _ops_handler(FakeServer(), status))
    assert cli.main(["check", "--api-url", BASE, "--token", token, "--fake"]) == code
    out = capsys.readouterr().out
    assert expected in out and "{'gpu': 3}" in out


def test_check_reports_unreachable_servers(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_client(monkeypatch, cli, down)
    assert cli.main(["check", "--api-url", BASE, "--fake"]) == 2
    assert "server unreachable" in capsys.readouterr().out


def test_run_command_processes_jobs_and_exits_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    from heritage_gpu.selftest import synthetic_photo

    server = FakeServer(blobs={"thumbs/1.png": synthetic_photo()})
    job = server.add("caption", {"asset_id": 1, "image_key": "thumbs/1.png"})
    _patch_client(monkeypatch, runner, server.handle)
    argv = ["run", "--api-url", BASE, "--token", TOKEN, "--fake", "--idle-exit", "0", "--preload"]
    assert cli.main([*argv, "--log-level", "WARNING"]) == 0
    assert job.status == "succeeded" and server.registrations == 1


def test_run_command_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer()
    job = server.add("caption", {"asset_id": 1, "image_key": "thumbs/missing.png"})
    _patch_client(monkeypatch, runner, server.handle)
    base = ["run", "--api-url", BASE, "--fake", "--idle-exit", "0", "--log-level", "ERROR"]
    assert cli.main([*base, "--token", TOKEN]) == 1  # a job failed
    assert job.status == "failed"
    assert cli.main([*base, "--token", "wrong"]) == 2  # refused

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_client(monkeypatch, runner, down)
    assert cli.main([*base, "--token", TOKEN]) == 2  # fail fast when the tunnel is down at start-up
