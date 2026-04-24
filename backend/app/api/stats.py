# app/api/stats.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.db.session import get_db_session
from app.services.stats import compute_dashboard_stats

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(verify_token)],
)


@router.get("/dashboard")
async def get_dashboard_stats(
    window_days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """All numbers the dashboard page needs in one round trip."""
    return await compute_dashboard_stats(db=db, time_window_days=window_days)