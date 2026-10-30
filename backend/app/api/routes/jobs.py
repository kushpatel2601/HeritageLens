from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import ServicesDep, SessionDep
from app.core.errors import NotFoundError
from app.core.security import require_ingest
from app.db.models import Job
from app.schemas.catalog import JobOut
from app.schemas.catalog import Page as PageOf
from app.services.jobs import labelled_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _labelled(job: Job, asset_title: str | None, site_name: str | None, site_slug: str | None) -> JobOut:
    return JobOut.model_validate(job).model_copy(
        update={"asset_title": asset_title, "site_name": site_name, "site_slug": site_slug}
    )


@router.get("", response_model=PageOf[JobOut], summary="Pipeline jobs (newest first)")
async def list_jobs(
    session: SessionDep,
    status: Literal["queued", "leased", "succeeded", "failed", "dead"] | None = None,
    type: str | None = None,
    queue: Literal["cpu", "gpu"] | None = None,
    asset_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageOf[JobOut]:
    conds = []
    if status:
        conds.append(Job.status == status)
    if type:
        conds.append(Job.type == type)
    if queue:
        conds.append(Job.queue == queue)
    if asset_id is not None:
        conds.append(Job.asset_id == asset_id)
    total = await session.scalar(select(func.count(Job.id)).where(*conds)) or 0
    query = labelled_jobs().where(*conds).order_by(Job.id.desc()).limit(limit).offset(offset)
    rows = (await session.execute(query)).all()
    return PageOf[JobOut](items=[_labelled(*r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(session: SessionDep, job_id: int) -> JobOut:
    row = (await session.execute(labelled_jobs().where(Job.id == job_id))).first()
    if row is None:
        raise NotFoundError(f"job {job_id} not found")
    return _labelled(*row)


@router.post(
    "/{job_id}/retry",
    response_model=JobOut,
    dependencies=[Depends(require_ingest)],
    summary="Re-queue a failed or dead-lettered job",
)
async def retry_job(services: ServicesDep, session: SessionDep, job_id: int) -> JobOut:
    return JobOut.model_validate(await services.queue.retry(session, job_id))
