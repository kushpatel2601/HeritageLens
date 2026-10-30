"""``heritage-gpu`` command line.

    heritage-gpu run       --api-url https://<tunnel>.trycloudflare.com --token ... [--preload]
    heritage-gpu check     --api-url ...      # reachability, token, queue depth, local GPU
    heritage-gpu selftest  [--fake]           # every engine once on synthetic inputs, offline

Every flag also reads ``HERITAGE_<NAME>`` from the environment (e.g. ``HERITAGE_TOKEN``), so
secrets need not appear in notebook cells or shell history.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import signal
import sys
from collections.abc import Sequence
from typing import Any

import httpx

from heritage_gpu import __version__
from heritage_gpu.client import ApiClient
from heritage_gpu.config import ALL_JOB_TYPES, WorkerConfig
from heritage_gpu.engines import build_engines
from heritage_gpu.engines._torch import describe_device
from heritage_gpu.errors import ApiError


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-url", help="HeritageLens server root or /api/v1 URL (HERITAGE_API_URL)")
    common.add_argument("--token", help="worker bearer token (HERITAGE_TOKEN)")
    common.add_argument("--name", help="worker name shown on the dashboard")
    common.add_argument("--types", help=f"comma-separated job types (default: {','.join(ALL_JOB_TYPES)})")
    common.add_argument("--device", choices=["auto", "cuda", "cpu"])
    common.add_argument("--fake", action="store_true", default=None, help="deterministic engines, no models/GPU")
    common.add_argument("--ocr-engine", choices=["tesseract", "vlm"])
    common.add_argument("--translator", choices=["auto", "indictrans2", "nllb"])
    common.add_argument("--splat-steps", type=int, help="Gaussian-splat optimisation steps (default 7000)")
    common.add_argument("--work-dir", help="scratch space for SfM / splat training")
    common.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    parser = argparse.ArgumentParser(
        prog="heritage-gpu", description="HeritageLens GPU worker (OCR, translation, captions, 3D twins)."
    )
    parser.add_argument("--version", action="version", version=f"heritage-gpu {__version__}")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", parents=[common], help="lease and process jobs until stopped")
    run.add_argument("--max-jobs", type=int, help="exit after this many jobs")
    run.add_argument("--idle-exit", type=float, help="exit after this many idle seconds")
    run.add_argument("--preload", action="store_true", help="load all models before leasing")
    sub.add_parser("check", parents=[common], help="verify server reachability, token and GPU")
    sub.add_parser("selftest", parents=[common], help="run each engine on synthetic inputs (offline)")
    return parser


def config_from_args(args: argparse.Namespace) -> WorkerConfig:
    overrides: dict[str, Any] = {
        "api_url": args.api_url,
        "token": args.token,
        "name": args.name,
        "device": args.device,
        "fake": args.fake,
        "ocr_engine": args.ocr_engine,
        "translator": args.translator,
        "splat_steps": args.splat_steps,
        "work_dir": args.work_dir,
        "max_jobs": getattr(args, "max_jobs", None),
        "idle_exit_seconds": getattr(args, "idle_exit", None),
    }
    if args.types:
        overrides["job_types"] = tuple(t.strip() for t in args.types.split(",") if t.strip())
    if overrides["work_dir"] is not None:
        from pathlib import Path

        overrides["work_dir"] = Path(overrides["work_dir"])
    return WorkerConfig.from_env(**overrides)


def cmd_check(config: WorkerConfig) -> int:
    print(f"device   : {'fake' if config.fake else describe_device(config.device)}")
    print(f"server   : {config.base_url}")
    with ApiClient(config.base_url, config.token, timeout=30, retries=1) as client:
        try:
            health = client.health()
            stats = client.stats()
            token_ok = client.token_is_valid()
        except (httpx.HTTPError, ApiError) as exc:
            print(f"FAIL     : server unreachable ({exc})")
            return 2
    print(f"status   : {health.get('status')} (database {health.get('database')}, version {health.get('version')})")
    print(f"workers  : {health.get('workers_online')}")
    print(f"queue    : {stats.get('queue_depth')}")
    print(f"token    : {'accepted' if token_ok else 'REJECTED - check HERITAGE_TOKEN / HL_WORKER_TOKEN'}")
    return 0 if token_ok and health.get("status") == "ok" else 1


def cmd_selftest(config: WorkerConfig) -> int:
    from heritage_gpu.selftest import run_selftest

    return 0 if run_selftest(build_engines(config)) else 1


def cmd_run(config: WorkerConfig, preload: bool) -> int:
    from heritage_gpu.runner import Runner

    with Runner(config) as runner:

        def _graceful(signum: int, _frame: object) -> None:
            logging.getLogger("heritage_gpu").warning("signal %d: finishing the current job, then exiting", signum)
            runner.stop()

        with contextlib.suppress(ValueError):  # not in the main thread (e.g. some notebook runners)
            signal.signal(signal.SIGTERM, _graceful)
        if preload:
            runner.preload()
        try:
            runner.register()
            stats = runner.run()
        except KeyboardInterrupt:
            print(f"\ninterrupted - {runner.stats.summary()}")
            return 130
        except ApiError as exc:
            print(f"server refused the worker: {exc}", file=sys.stderr)
            return 2
        except httpx.HTTPError as exc:
            print(f"server unreachable at {config.base_url}: {exc}", file=sys.stderr)
            return 2
    return 0 if stats.failed == 0 else 1


def _safe_streams() -> None:
    """Never crash on Indic text when stdout is a legacy-codepage pipe (e.g. Windows cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    _safe_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    logging.basicConfig(
        level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = config_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "check":
        return cmd_check(config)
    if args.command == "selftest":
        return cmd_selftest(config)
    return cmd_run(config, preload=args.preload)


if __name__ == "__main__":
    sys.exit(main())
