# app/api/visual.py
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.db.session import get_db_session
from app.models.asset import Asset
from app.models.visual import CrawlWatchlist, VisualCandidate
from app.schemas.visual import (
    DiscoverRequest,
    DiscoverResponse,
    VisualCandidateList,
    VisualCandidateRead,
    WatchlistCreate,
    WatchlistList,
    WatchlistRead,
)
from app.workers.visual_task import discover_visual_candidates

router = APIRouter(
    prefix="",  # endpoints split between /assets/{id}/... and /visual/...
    tags=["visual-discovery"],
    dependencies=[Depends(verify_token)],
)


# ---------------------------------------------------------------------------
# Asset-scoped: discovery + candidate listing
# ---------------------------------------------------------------------------

@router.post(
    "/assets/{asset_id}/visual-discover",
    response_model=DiscoverResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_visual_discovery(
    asset_id: UUID,
    body: DiscoverRequest,
    db: AsyncSession = Depends(get_db_session),
) -> DiscoverResponse:
    """Kick off a visual-discovery scan for the asset."""
    asset = await db.get(Asset, str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if asset.fingerprint_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Asset must be fingerprinted (status=ready) before discovery",
        )

    task = discover_visual_candidates.delay(
        asset_id=str(asset_id),
        query=body.query,
        max_candidates=body.max_candidates,
    )
    return DiscoverResponse(task_id=task.id, status="queued", asset_id=asset_id)


@router.get(
    "/assets/{asset_id}/visual-candidates",
    response_model=VisualCandidateList,
)
async def list_visual_candidates(
    asset_id: UUID,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
) -> VisualCandidateList:
    """List visual candidates for an asset, highest-score first."""
    result = await db.execute(
        select(VisualCandidate)
        .where(VisualCandidate.asset_id == str(asset_id))
        .order_by(VisualCandidate.visual_score.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return VisualCandidateList(
        asset_id=asset_id,
        total=len(rows),
        items=[VisualCandidateRead.model_validate(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# Candidate operations
# ---------------------------------------------------------------------------

@router.delete("/visual/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_candidate(
    candidate_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Dismiss (delete) a single candidate that's a false positive."""
    row = await db.get(VisualCandidate, str(candidate_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------

@router.get("/visual/watchlists", response_model=WatchlistList)
async def list_watchlists(
    db: AsyncSession = Depends(get_db_session),
) -> WatchlistList:
    result = await db.execute(select(CrawlWatchlist).order_by(CrawlWatchlist.created_at.desc()))
    rows = list(result.scalars().all())
    return WatchlistList(
        total=len(rows),
        items=[WatchlistRead.model_validate(r) for r in rows],
    )


@router.post(
    "/visual/watchlists",
    response_model=WatchlistRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_watchlist(
    body: WatchlistCreate,
    db: AsyncSession = Depends(get_db_session),
) -> WatchlistRead:
    row = CrawlWatchlist(
        id=str(uuid4()),
        label=body.label,
        root_url=body.root_url,
        platform=body.platform,
        enabled=body.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return WatchlistRead.model_validate(row)


@router.delete("/visual/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    watchlist_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    row = await db.get(CrawlWatchlist, str(watchlist_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    await db.delete(row)
    await db.commit()