"""`heritagelens` command-line interface: schema migrations, seeding, workers and maintenance."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import select

from app.core.config import BACKEND_DIR, Settings, get_settings
from app.core.logging import configure_logging
from app.db.models import Asset, Chunk, Site
from app.db.session import Database
from app.services.catalog import index_site
from app.services.jobs import JobQueue
from app.services.pipeline import JobContext, enqueue_index
from app.services.storage import build_storage
from app.workers.local import LocalWorker


@contextlib.asynccontextmanager
async def job_context(settings: Settings) -> AsyncIterator[JobContext]:
    db = Database(settings)
    if settings.is_sqlite and settings.auto_create_schema:
        await db.create_all()
    try:
        yield JobContext(settings, db, build_storage(settings), JobQueue(settings))
    finally:
        await db.dispose()


# ---------------------------------------------------------------- commands
def cmd_migrate(settings: Settings, args: argparse.Namespace) -> int:
    if settings.is_sqlite:
        # The SQLite quick-start has no pgvector/GIN indexes to manage: create the schema directly.
        async def create() -> None:
            db = Database(settings)
            await db.create_all()
            await db.dispose()

        asyncio.run(create())
        print("sqlite schema ready")
        return 0
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["configure_logger"] = False  # keep the app's logging setup
    command.upgrade(cfg, args.revision)
    print(f"postgres schema at {args.revision}")
    return 0


def cmd_seed(settings: Settings, args: argparse.Namespace) -> int:
    from app.seed.loader import run_seed

    async def run() -> dict[str, object]:
        async with job_context(settings) as ctx:
            report = await run_seed(ctx, offline=args.offline, process=not args.no_process)
        return report.as_dict()

    print(json.dumps(asyncio.run(run()), indent=2))
    return 0


def cmd_worker(settings: Settings, args: argparse.Namespace) -> int:
    async def run() -> None:
        async with job_context(settings) as ctx:
            worker = LocalWorker(ctx, queue="cpu", concurrency=args.concurrency, name=args.name)
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError):  # Windows: KeyboardInterrupt path below
                    loop.add_signal_handler(sig, worker.request_stop)
            await worker.run_forever()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())
    return 0


def cmd_reindex(settings: Settings, args: argparse.Namespace) -> int:
    """Recompute site keys/embeddings and re-run indexing for every asset (e.g. after changing the
    embedding model)."""

    async def run() -> dict[str, int]:
        async with job_context(settings) as ctx:
            async with ctx.db.sessionmaker() as s:
                sites = (await s.scalars(select(Site))).all()
                for site in sites:
                    await index_site(site, settings)
                asset_ids = [] if args.sites_only else (await s.scalars(select(Asset.id).order_by(Asset.id))).all()
                for asset_id in asset_ids:
                    await enqueue_index(ctx, s, asset_id, priority=150)
                await s.commit()
            processed = 0
            if asset_ids and not args.no_process:
                processed = await LocalWorker(ctx, name="reindex worker").drain()
            return {"sites": len(sites), "assets": len(asset_ids), "jobs_processed": processed}

    print(json.dumps(asyncio.run(run()), indent=2))
    return 0


def cmd_openapi(settings: Settings, args: argparse.Namespace) -> int:
    from app.main import create_app

    spec = json.dumps(create_app(settings).openapi(), indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(spec + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(spec + "\n")
    return 0


def cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, proxy_headers=True)
    return 0


def cmd_export_lean_model(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.embeddings import MODEL_CACHE_DIR
    from app.services.lean_export import export_lean_model

    async def archive_texts() -> list[str]:
        db = Database(settings)
        try:
            async with db.sessionmaker() as s:
                rows = (await s.execute(select(Chunk.text, Chunk.translation).limit(args.archive_texts))).all()
        finally:
            await db.dispose()
        return [t for row in rows for t in row if t]

    extra = asyncio.run(archive_texts()) if args.archive_texts else []
    out = Path(args.out) if args.out else settings.lean_model_dir
    report = export_lean_model(settings.text_embed_model, out, cache_dir=MODEL_CACHE_DIR, extra_texts=extra)
    summary = {
        "out_dir": str(report.out_dir),
        "model": report.manifest.model,
        "files_mb": report.files_mb,
        "texts_checked": report.texts_checked,
        "min_cosine_vs_fastembed": report.min_cosine,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heritagelens", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("migrate", help="create / upgrade the database schema")
    p.add_argument("--revision", default="head")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("seed", help="load the sample archive (idempotent)")
    p.add_argument("--offline", action="store_true", help="never download photos; use the local cache only")
    p.add_argument("--no-process", action="store_true", help="only enqueue jobs; leave them to running workers")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("worker", help="run a CPU worker pulling from the job queue")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_worker)

    p = sub.add_parser("reindex", help="re-embed sites and re-index all assets")
    p.add_argument("--sites-only", action="store_true")
    p.add_argument("--no-process", action="store_true")
    p.set_defaults(func=cmd_reindex)

    p = sub.add_parser("openapi", help="export the OpenAPI document (used to type the frontend client)")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_openapi)

    p = sub.add_parser("serve", help="run the API with uvicorn")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser(
        "export-lean-model",
        help="rewrite the text model for 512 MB hosts (same vectors, ~1/3 of the RAM); needs the ml+export extras",
    )
    p.add_argument("--out", default=None, help="target directory (default: HL_LEAN_MODEL_DIR)")
    p.add_argument(
        "--archive-texts", type=int, default=0, metavar="N", help="also verify parity on N chunks from the database"
    )
    p.set_defaults(func=cmd_export_lean_model)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    return int(args.func(settings, args))


if __name__ == "__main__":
    raise SystemExit(main())
