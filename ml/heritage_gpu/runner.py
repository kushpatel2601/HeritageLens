"""The worker loop: register -> lease -> (heartbeat while) run engine -> complete / fail.

Design notes

* Pull-based and outbound-only, so a Colab VM behind NAT works through any HTTPS tunnel.
* A background heartbeat thread keeps the lease alive while a model loads or a splat trains; if the
  server answers 404/409 the lease is gone (expired and re-queued, or the job was cancelled) and the
  engine is stopped at its next ``check_cancelled()`` instead of wasting GPU time.
* Failures carry an explicit retry decision: bad inputs are dead-lettered at once, transient ones
  (CUDA OOM, network) are retried by the server with backoff, capped at its max attempts.
* An engine that cannot load (missing binary, gated model) is disabled for this worker and its job
  handed back, so other workers - or the CPU fallback - can take it.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal

import httpx

from heritage_gpu.client import ApiClient, LeasedJob
from heritage_gpu.config import WorkerConfig
from heritage_gpu.engines import Engine, build_engines
from heritage_gpu.engines._torch import describe_device, free_accelerator_memory
from heritage_gpu.errors import (
    ApiError,
    InvalidResultError,
    JobCancelledError,
    JobError,
    LeaseLostError,
    NotRegisteredError,
)

log = logging.getLogger("heritage_gpu")

Outcome = Literal["succeeded", "failed", "lost"]


@dataclass
class RunStats:
    succeeded: int = 0
    failed: int = 0
    lost: int = 0
    busy_seconds: float = 0.0
    by_type: Counter[str] = field(default_factory=Counter)

    @property
    def processed(self) -> int:
        return self.succeeded + self.failed + self.lost

    def record(self, job_type: str, outcome: Outcome, seconds: float) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)
        self.by_type[f"{job_type}:{outcome}"] += 1
        self.busy_seconds += seconds

    def summary(self) -> str:
        return (
            f"{self.succeeded} succeeded, {self.failed} failed, {self.lost} lost "
            f"in {self.busy_seconds:.0f}s of GPU time"
        )


def classify_failure(exc: BaseException) -> tuple[str, bool]:
    """(error message for the server, retryable?)."""
    if isinstance(exc, JobError):
        return str(exc), exc.retryable
    if type(exc).__name__ == "OutOfMemoryError" or "out of memory" in str(exc).lower():
        free_accelerator_memory()
        return f"GPU out of memory: {exc}"[:1000], True
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=-4))
    return f"{type(exc).__name__}: {exc}"[:1000] + "\n" + tb[-2500:], True


class Heartbeat:
    """Extends the lease every ``interval`` seconds on a daemon thread while a job runs."""

    def __init__(self, client: ApiClient, worker_id: str, job_id: int, interval: float) -> None:
        self.lost = threading.Event()
        self._client, self._worker_id, self._job_id, self._interval = client, worker_id, job_id, interval
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"heartbeat-{job_id}", daemon=True)

    def __enter__(self) -> Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._halt.set()
        self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._halt.wait(self._interval):
            try:
                self._client.heartbeat(self._worker_id, self._job_id)
            except ApiError as exc:
                if isinstance(exc, LeaseLostError) or exc.status == 404:
                    log.warning("job %s: lease lost (%s)", self._job_id, exc.detail)
                    self.lost.set()
                    return
                log.warning("job %s: heartbeat rejected: %s", self._job_id, exc)
            except Exception as exc:  # network blips: keep trying until the lease runs out
                log.warning("job %s: heartbeat failed: %s", self._job_id, exc)


class LeaseIO:
    """:class:`heritage_gpu.engines.JobIO` bound to one leased job."""

    def __init__(self, client: ApiClient, worker_id: str, job: LeasedJob, heartbeat: Heartbeat) -> None:
        self.job_id = job.id
        self._client, self._worker_id, self._job, self._heartbeat = client, worker_id, job, heartbeat

    def check_cancelled(self) -> None:
        if self._heartbeat.lost.is_set():
            raise JobCancelledError(f"lease on job {self.job_id} was lost")

    def fetch(self, key: str) -> bytes:
        self.check_cancelled()
        try:
            return self._client.blob(key)
        except ApiError as exc:
            if exc.status == 404:
                raise JobError(f"input {key} is no longer available on the server", retryable=False) from exc
            raise

    def upload_artifact(self, filename: str, data: bytes) -> dict[str, Any]:
        self.check_cancelled()
        try:
            return self._client.upload_artifact(self._worker_id, self.job_id, filename, data)
        except LeaseLostError as exc:
            raise JobCancelledError(str(exc)) from exc
        except ApiError as exc:
            if exc.status in (413, 415):
                raise JobError(f"server rejected the artifact: {exc.detail}", retryable=False) from exc
            raise

    def progress(self, message: str) -> None:
        log.info("job %s [%s] %s", self.job_id, self._job.type, message)


class Runner:
    def __init__(
        self,
        config: WorkerConfig,
        *,
        client: ApiClient | None = None,
        engines: dict[str, Engine] | None = None,
        device_label: str | None = None,
    ) -> None:
        self.config = config
        self.client = client or ApiClient(
            config.base_url, config.token, timeout=config.http_timeout_seconds, retries=config.http_retries
        )
        self.engines: dict[str, Engine] = dict(build_engines(config) if engines is None else engines)
        self.device_label = device_label
        self.stats = RunStats()
        self.worker_id: str | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ lifecycle
    def stop(self) -> None:
        """Finish the current job, then exit the loop (e.g. on SIGTERM)."""
        self._stop.set()

    @property
    def job_types(self) -> list[str]:
        return sorted(self.engines)

    def register(self) -> str:
        device = self.device_label or (
            "synthetic (fake engines)" if self.config.fake else describe_device(self.config.device)
        )
        self.worker_id = self.client.register(self.config.name, self.job_types, device)
        log.info("registered as %s on %s; handling %s", self.worker_id, device, ", ".join(self.job_types))
        return self.worker_id

    def preload(self) -> None:
        """Load every model up front so the first job of each type is not slowed by downloads."""
        for job_type, engine in list(self.engines.items()):
            started = time.monotonic()
            try:
                engine.ensure_loaded()
            except Exception as exc:
                self._disable(job_type, exc)
            else:
                log.info("loaded %s for %s in %.1fs", engine.name, job_type, time.monotonic() - started)

    def _disable(self, job_type: str, exc: BaseException) -> None:
        self.engines.pop(job_type, None)
        log.error("%s engine unavailable, no longer leasing %s jobs: %s", job_type, job_type, exc)

    def __enter__(self) -> Runner:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.client.close()

    # ------------------------------------------------------------------ main loop
    def _wait(self, seconds: float) -> None:
        self._stop.wait(seconds)

    def _lease(self) -> list[LeasedJob]:
        if self.worker_id is None:
            self.register()
        assert self.worker_id is not None
        try:
            return self.client.lease(self.worker_id, self.job_types, limit=1, lease_seconds=self.config.lease_seconds)
        except NotRegisteredError:
            log.warning("the server no longer knows this worker (database reset?) - registering again")
            self.worker_id = None
            return []

    def run(self) -> RunStats:
        cfg = self.config
        delay = cfg.poll_min_seconds
        idle_since = time.monotonic()
        while not self._stop.is_set():
            if not self.engines:
                log.error("no engines left to run - stopping")
                break
            if cfg.max_jobs is not None and self.stats.processed >= cfg.max_jobs:
                log.info("processed %d jobs (--max-jobs) - stopping", self.stats.processed)
                break
            try:
                jobs = self._lease()
            except ApiError as exc:
                if exc.status in (401, 403):
                    raise  # wrong token: retrying will not help
                log.warning("lease failed: %s", exc)
                jobs = []
            except httpx.HTTPError as exc:
                log.warning("API unreachable (%s); retrying in %.0fs", exc.__class__.__name__, delay)
                jobs = []
            if not jobs:
                if cfg.idle_exit_seconds is not None and time.monotonic() - idle_since >= cfg.idle_exit_seconds:
                    log.info("idle for %.0fs - stopping", cfg.idle_exit_seconds)
                    break
                self._wait(delay)
                delay = min(delay * 2, cfg.poll_max_seconds)
                continue
            delay = cfg.poll_min_seconds
            for job in jobs:
                self.process(job)
            idle_since = time.monotonic()
        log.info("worker stopped: %s", self.stats.summary())
        return self.stats

    # ------------------------------------------------------------------ one job
    def process(self, job: LeasedJob) -> Outcome:
        assert self.worker_id is not None
        started = time.monotonic()
        log.info("job %s [%s] started (attempt %d)", job.id, job.type, job.attempts)
        with Heartbeat(self.client, self.worker_id, job.id, self.config.heartbeat_seconds) as heartbeat:
            outcome = self._execute(job, LeaseIO(self.client, self.worker_id, job, heartbeat), heartbeat)
        elapsed = time.monotonic() - started
        self.stats.record(job.type, outcome, elapsed)
        log.info("job %s [%s] %s in %.1fs", job.id, job.type, outcome, elapsed)
        return outcome

    def _execute(self, job: LeasedJob, io: LeaseIO, heartbeat: Heartbeat) -> Outcome:
        engine = self.engines.get(job.type)
        if engine is None:
            return self._fail(job, f"worker {self.config.name} has no engine for {job.type}", retryable=True)
        try:
            engine.ensure_loaded()
        except Exception as exc:
            self._disable(job.type, exc)
            return self._fail(job, f"{job.type} engine unavailable on {self.config.name}: {exc}", retryable=True)
        try:
            result = engine.run(job.payload, io)
        except KeyboardInterrupt:
            self._fail(job, "worker interrupted", retryable=True)
            raise
        except JobCancelledError as exc:
            log.warning("job %s abandoned: %s", job.id, exc)
            return "lost"
        except Exception as exc:
            message, retryable = classify_failure(exc)
            log.error(
                "job %s failed (%s): %s", job.id, "will retry" if retryable else "permanent", message.splitlines()[0]
            )
            return self._fail(job, message, retryable=retryable)
        if heartbeat.lost.is_set():
            return "lost"
        assert self.worker_id is not None
        try:
            self.client.complete(self.worker_id, job.id, result)
        except LeaseLostError as exc:
            log.warning("job %s finished after its lease was lost: %s", job.id, exc.detail)
            return "lost"
        except InvalidResultError as exc:
            log.error("server rejected the result of job %s: %s", job.id, exc.detail)
            return "failed"
        return "succeeded"

    def _fail(self, job: LeasedJob, message: str, *, retryable: bool) -> Outcome:
        assert self.worker_id is not None
        try:
            self.client.fail(self.worker_id, job.id, message, retryable=retryable)
        except LeaseLostError:
            return "lost"
        except (ApiError, httpx.HTTPError) as exc:
            log.warning("could not report the failure of job %s: %s", job.id, exc)
        return "failed"
