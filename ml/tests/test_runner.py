from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fakeserver import BASE, TOKEN, FakeServer

from heritage_gpu.client import ApiClient, LeasedJob
from heritage_gpu.config import WorkerConfig
from heritage_gpu.engines import Engine, JobIO, build_engines
from heritage_gpu.errors import ApiError, JobError
from heritage_gpu.runner import Runner, RunStats, classify_failure
from heritage_gpu.selftest import synthetic_page, synthetic_photo

CAPTION = {"engine": "scripted", "caption": "A carved stone balcony"}


class Scripted(Engine):
    """A test engine whose behaviour is a plain function of (payload, io)."""

    def __init__(
        self,
        job_type: str,
        fn: Callable[[dict[str, Any], JobIO], dict[str, Any]] = lambda p, io: CAPTION,
        *,
        load_error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.job_type = job_type  # type: ignore[misc]
        self._fn, self._load_error = fn, load_error
        self.loads = 0

    @property
    def name(self) -> str:
        return "scripted"

    def load(self) -> None:
        self.loads += 1
        if self._load_error is not None:
            raise self._load_error

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        return self._fn(payload, io)


def make_config(**overrides: Any) -> WorkerConfig:
    base: dict[str, Any] = {
        "api_url": BASE,
        "token": TOKEN,
        "name": "pytest",
        "fake": True,
        "poll_min_seconds": 0.001,
        "poll_max_seconds": 0.005,
        "idle_exit_seconds": 0.0,
        "heartbeat_seconds": 0.02,
        "http_retries": 0,
    }
    base.update(overrides)
    return WorkerConfig.from_env({}, **base)


def make_runner(
    server: FakeServer,
    engines: dict[str, Engine] | None = None,
    *,
    transport: Callable[[httpx.Request], httpx.Response] | None = None,
    token: str = TOKEN,
    **overrides: Any,
) -> Runner:
    config = make_config(**overrides)
    http = httpx.Client(transport=httpx.MockTransport(transport or server.handle))
    client = ApiClient(config.base_url, token, http=http, retries=0, sleep=lambda _s: None)
    return Runner(config, client=client, engines=build_engines(config) if engines is None else engines)


def test_fake_engines_process_every_job_type_end_to_end() -> None:
    server = FakeServer(blobs={"pages/1/1.png": synthetic_page(), "originals/3/a.png": synthetic_photo()})
    server.blobs["thumbs/2.png"] = server.blobs["originals/3/a.png"]
    jobs = [
        server.add("ocr", {"asset_id": 1, "lang_hint": "gu", "pages": [{"page_no": 1, "image_key": "pages/1/1.png"}]}),
        server.add("translate", {"asset_id": 4, "src_lang": "gu", "items": [{"chunk_id": 9, "text": "રાણીની વાવ"}]}),
        server.add("caption", {"asset_id": 2, "image_key": "thumbs/2.png"}),
        server.add(
            "reconstruct3d",
            {"site_id": 1, "method": "depth-relief", "images": [{"asset_id": 3, "image_key": "originals/3/a.png"}]},
        ),
    ]
    with make_runner(server) as runner:
        stats = runner.run()

    assert (stats.succeeded, stats.failed, stats.lost) == (4, 0, 0)
    assert stats.by_type == {f"{t}:succeeded": 1 for t in ("ocr", "translate", "caption", "reconstruct3d")}
    assert server.registrations == 1 and server.workers["gpu-test-1"] == [
        "caption",
        "ocr",
        "reconstruct3d",
        "translate",
    ]
    ocr, translate, caption, twin = (j.result for j in jobs)
    assert ocr and ocr["pages"][0]["page_no"] == 1 and "page 1" in ocr["pages"][0]["text"]
    assert translate and translate["items"] == [{"chunk_id": 9, "translation": "[synthetic Gujarati gloss] રાણીની વાવ"}]
    assert caption and caption["caption"].endswith("(synthetic caption)")
    assert twin and twin["format"] == "ply" and twin["source_asset_ids"] == [3]
    assert server.artifacts[twin["artifact_key"]].startswith(b"ply\nformat binary_little_endian")


def test_missing_inputs_are_dead_lettered() -> None:
    server = FakeServer()
    job = server.add("caption", {"asset_id": 1, "image_key": "thumbs/deleted.png"})
    with make_runner(server) as runner:
        runner.run()
    assert job.status == "failed" and job.retryable is False and "no longer available" in (job.error or "")


@pytest.mark.parametrize(
    ("exc", "retryable", "message"),
    [
        (JobError("unsupported script", retryable=False), False, "unsupported script"),
        (RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"), True, "GPU out of memory"),
        (ValueError("tensor shape mismatch"), True, "ValueError: tensor shape mismatch"),
    ],
)
def test_engine_failures_carry_a_retry_decision(exc: Exception, retryable: bool, message: str) -> None:
    def explode(payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        raise exc

    server = FakeServer()
    job = server.add("caption", {})
    with make_runner(server, {"caption": Scripted("caption", explode)}) as runner:
        stats = runner.run()
    assert stats.failed == 1 and job.status == "failed"
    assert job.retryable is retryable and (job.error or "").startswith(message)


def test_classify_failure_includes_a_traceback_for_unexpected_errors() -> None:
    try:
        {}["missing"]
    except KeyError as exc:
        message, retryable = classify_failure(exc)
    assert retryable and message.startswith("KeyError: 'missing'") and "Traceback" in message

    class OutOfMemoryError(Exception):  # torch.cuda.OutOfMemoryError is matched by name: no torch import
        pass

    assert classify_failure(OutOfMemoryError("allocator"))[1] is True


def test_rejected_artifacts_are_not_retried() -> None:
    def upload_obj(payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        io.upload_artifact("mesh.obj", b"v 0 0 0")
        raise AssertionError("unreachable")

    server = FakeServer()
    job = server.add("reconstruct3d", {})
    with make_runner(server, {"reconstruct3d": Scripted("reconstruct3d", upload_obj)}) as runner:
        runner.run()
    assert job.retryable is False and "server rejected the artifact" in (job.error or "")


def test_heartbeats_keep_long_jobs_alive() -> None:
    def slow(payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        for _ in range(15):
            io.check_cancelled()
            time.sleep(0.01)
        return CAPTION

    server = FakeServer()
    job = server.add("caption", {})
    with make_runner(server, {"caption": Scripted("caption", slow)}) as runner:
        runner.run()
    assert job.status == "succeeded" and server.heartbeats >= 2


def test_a_lost_lease_stops_the_engine_and_skips_completion() -> None:
    progress: list[int] = []

    def long_training(payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        for step in range(500):
            io.check_cancelled()
            progress.append(step)
            time.sleep(0.005)
        return CAPTION

    server = FakeServer()
    job = server.add("caption", {})
    server.lose_lease_on_heartbeat.add(job.id)
    with make_runner(server, {"caption": Scripted("caption", long_training)}, max_jobs=1) as runner:
        stats = runner.run()
    assert stats.lost == 1 and stats.succeeded == 0
    assert len(progress) < 500 and job.result is None and job.status == "queued"
    assert not any(r.endswith("/complete") for r in server.requests)


def test_completion_conflicts_and_rejected_results() -> None:
    server = FakeServer()
    late, invalid = server.add("caption", {}), server.add("caption", {})
    server.lose_lease_on_complete.add(late.id)
    server.reject_results.add(invalid.id)
    with make_runner(server, {"caption": Scripted("caption")}, max_jobs=2) as runner:
        stats = runner.run()
    assert (stats.lost, stats.failed) == (1, 1)
    assert late.owner == "gpu-other-worker" and late.result is None and invalid.status == "dead"


def test_engines_that_cannot_load_are_disabled_and_their_jobs_handed_back() -> None:
    server = FakeServer()
    first, second = server.add("ocr", {}), server.add("ocr", {})
    broken = Scripted("ocr", load_error=RuntimeError("tesseract is not installed"))
    with make_runner(server, {"ocr": broken}, idle_exit_seconds=None) as runner:
        stats = runner.run()  # exits by itself: no engines left
    assert stats.failed == 1 and runner.engines == {}
    assert first.retryable is True and "engine unavailable" in (first.error or "")
    assert second.status == "queued"  # left for another worker


def test_preload_loads_models_once_and_drops_broken_ones() -> None:
    good = Scripted("caption")
    broken = Scripted("ocr", load_error=OSError("gated model"))
    runner = make_runner(FakeServer(), {"caption": good, "ocr": broken})
    runner.preload()
    runner.preload()
    assert runner.job_types == ["caption"] and good.loads == 1


def test_max_jobs_and_stop_end_the_loop() -> None:
    server = FakeServer()
    jobs = [server.add("caption", {}) for _ in range(3)]
    with make_runner(server, {"caption": Scripted("caption")}, max_jobs=2, idle_exit_seconds=None) as runner:
        assert runner.run().processed == 2
    assert [j.status for j in jobs] == ["succeeded", "succeeded", "queued"]

    holder: list[Runner] = []

    def stop_after_this(payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        holder[0].stop()
        return CAPTION

    with make_runner(server, {"caption": Scripted("caption", stop_after_this)}, idle_exit_seconds=None) as runner:
        holder.append(runner)
        assert runner.run().succeeded == 1  # the current job still completes
    assert jobs[2].status == "succeeded"


def test_worker_re_registers_after_a_server_reset() -> None:
    server = FakeServer(forget_workers_once=True)
    job = server.add("caption", {})
    with make_runner(server, {"caption": Scripted("caption")}, idle_exit_seconds=0.2) as runner:
        runner.run()
    assert server.registrations == 2 and job.status == "succeeded" and runner.worker_id == "gpu-test-2"


def test_network_outages_are_survived() -> None:
    server = FakeServer()
    job = server.add("caption", {})
    outages = iter([True, True])

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lease") and next(outages, False):
            raise httpx.ConnectError("tunnel restarting")
        return server.handle(request)

    with make_runner(server, {"caption": Scripted("caption")}, transport=flaky, idle_exit_seconds=0.2) as runner:
        runner.run()
    assert job.status == "succeeded"


def test_a_wrong_token_is_fatal() -> None:
    server = FakeServer()
    with make_runner(server, {"caption": Scripted("caption")}, token="wrong") as runner, pytest.raises(ApiError) as err:
        runner.run()
    assert err.value.status == 401


def test_interrupts_hand_the_job_back() -> None:
    def interrupted(payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        raise KeyboardInterrupt

    server = FakeServer()
    job = server.add("caption", {})
    with make_runner(server, {"caption": Scripted("caption", interrupted)}) as runner, pytest.raises(KeyboardInterrupt):
        runner.run()
    assert job.status == "failed" and job.retryable is True and job.error == "worker interrupted"


def test_jobs_of_unknown_type_are_returned() -> None:
    server = FakeServer()
    job = server.add("translate", {})
    runner = make_runner(server, {"caption": Scripted("caption")})
    runner.register()
    server.jobs[job.id].status, server.jobs[job.id].owner = "leased", runner.worker_id
    assert runner.process(LeasedJob(job.id, "translate", {}, 1)) == "failed"
    assert job.retryable is True and "no engine for translate" in (job.error or "")


def test_run_stats_summary() -> None:
    stats = RunStats()
    stats.record("ocr", "succeeded", 1.5)
    stats.record("ocr", "failed", 0.5)
    stats.record("caption", "lost", 2.0)
    assert stats.processed == 3 and stats.by_type["ocr:failed"] == 1
    assert stats.summary() == "1 succeeded, 1 failed, 1 lost in 4s of GPU time"
