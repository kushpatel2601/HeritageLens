from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.deps import ServicesDep, SessionDep
from app.api.files import blob_response
from app.api.routes.sites import twin_out
from app.core.errors import NotFoundError
from app.db.models import Site, Twin
from app.schemas.catalog import TwinOut

router = APIRouter(prefix="/twins", tags=["3d twins"])

MEDIA = {"ply": "application/octet-stream", "splat": "application/octet-stream", "glb": "model/gltf-binary"}


@router.get("", response_model=list[TwinOut], summary="Gallery of digital twins")
async def list_twins(session: SessionDep) -> list[TwinOut]:
    rows = (await session.scalars(select(Twin).join(Site, Site.id == Twin.site_id).order_by(Twin.id.desc()))).all()
    return [twin_out(t) for t in rows]


@router.get("/{twin_id}", response_model=TwinOut)
async def get_twin(session: SessionDep, twin_id: int) -> TwinOut:
    twin = await session.get(Twin, twin_id)
    if twin is None:
        raise NotFoundError(f"twin {twin_id} not found")
    return twin_out(twin)


@router.get("/{twin_id}/file", response_class=Response, summary="Point cloud (.ply), splat (.splat) or mesh (.glb)")
async def twin_file(request: Request, services: ServicesDep, session: SessionDep, twin_id: int) -> Response:
    twin = await session.get(Twin, twin_id)
    if twin is None:
        raise NotFoundError(f"twin {twin_id} not found")
    return await blob_response(
        request,
        services.storage,
        twin.storage_key,
        media_type=MEDIA.get(twin.format),
        immutable=True,
        etag=f"twin-{twin.id}-{int(twin.updated_at.timestamp())}",
    )
