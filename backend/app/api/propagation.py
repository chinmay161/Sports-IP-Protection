from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.propagation import PropagationGraph, PropagationSummary, PropagationTimeline
from app.services.propagation import PropagationError, get_graph, get_summary, get_timeline

router = APIRouter()


@router.get("/{match_id}/graph", response_model=PropagationGraph)
async def propagation_graph(
    match_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> PropagationGraph:
    try:
        return await get_graph(match_id, db)
    except PropagationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{match_id}/timeline", response_model=PropagationTimeline)
async def propagation_timeline(
    match_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> PropagationTimeline:
    try:
        return await get_timeline(match_id, db)
    except PropagationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{asset_id}/summary", response_model=PropagationSummary)
async def propagation_summary(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> PropagationSummary:
    try:
        return await get_summary(asset_id, db)
    except PropagationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
