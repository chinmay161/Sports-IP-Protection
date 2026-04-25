# app/api/visual.py
from uuid import UUID, uuid4
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
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
    VisualFrameList,
    VisualFrameRead,
    WatchlistCreate,
    WatchlistList,
    WatchlistRead,
)
from app.workers.visual_task import discover_visual_candidates

router = APIRouter(
    prefix="",
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


# ---------------------------------------------------------------------------
# Asset Frames (NEW)
# ---------------------------------------------------------------------------

@router.get(
    "/assets/{asset_id}/frames",
    response_model=VisualFrameList,
)
async def list_asset_frames(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> VisualFrameList:
    """List visual frames extracted from an asset during indexing."""
    from app.models.visual import VisualAssetFrame  # local import to avoid cycle issues

    result = await db.execute(
        select(VisualAssetFrame)
        .where(VisualAssetFrame.asset_id == str(asset_id))
        .order_by(VisualAssetFrame.timestamp_ms.asc())
    )
    rows = list(result.scalars().all())

    return VisualFrameList(
        asset_id=asset_id,
        total=len(rows),
        items=[
            VisualFrameRead(
                id=UUID(r.id),
                asset_id=UUID(r.asset_id),
                timestamp_ms=r.timestamp_ms,
                phash=r.phash,
                has_clip_vector=r.clip_vector is not None,
                created_at=r.created_at,
            )
            for r in rows
        ],
    )


@router.get("/assets/{asset_id}/frames/{frame_id}/image")
async def get_asset_frame_image(
    asset_id: UUID,
    frame_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Stream a single extracted frame as a JPEG."""
    from app.models.visual import VisualAssetFrame

    frame = await db.get(VisualAssetFrame, str(frame_id))
    if frame is None or frame.asset_id != str(asset_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame not found")

    if not frame.frame_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame has no image on disk")

    path = Path(frame.frame_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame file missing on disk")

    return FileResponse(path, media_type="image/jpeg")