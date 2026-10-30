from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import ServicesDep, SessionDep
from app.core.errors import AppError
from app.schemas.search import SearchResponse
from app.services.search import SearchFilters

router = APIRouter(tags=["search"])


def parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw:
        return None
    try:
        w, s, e, n = (float(x) for x in raw.split(","))
    except ValueError:
        raise AppError("bbox must be 'west,south,east,north'", status_code=422, title="Invalid parameter") from None
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= n <= 90):
        raise AppError("bbox out of range", status_code=422, title="Invalid parameter")
    return w, s, e, n


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid cross-script search (keyword + phonetic + semantic, fused with RRF)",
    description=(
        "Query in any script or spelling: `rani ki vav`, `રાણી કી વાવ` and `रानी की वाव` retrieve the same "
        "passages. Results are grouped per document, with highlighted snippets, translations, matching "
        "sites and (for English queries) visually similar photos via CLIP."
    ),
)
async def search(
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=300)],
    lang: Annotated[str | None, Query(max_length=8)] = None,
    kind: Annotated[list[Literal["photo", "scan", "pdf", "deck", "journal", "story"]] | None, Query()] = None,
    site_id: int | None = None,
    journey_id: int | None = None,
    category: str | None = None,
    era_from: int | None = None,
    era_to: int | None = None,
    bbox: Annotated[str | None, Query(description="west,south,east,north")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=500)] = 0,
) -> SearchResponse:
    filters = SearchFilters(
        language=lang,
        kinds=list(kind or []),
        site_id=site_id,
        journey_id=journey_id,
        category=category,
        era_from=era_from,
        era_to=era_to,
        bbox=parse_bbox(bbox),
    )
    return await services.search.search(session, q.strip(), filters, limit=limit, offset=offset)
