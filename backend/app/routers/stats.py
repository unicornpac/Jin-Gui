"""访问量统计 —— 管理端卡片用。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import verify_admin
from ..models import PageVisit

router = APIRouter()

TRACKED_PAGES = ("/user", "/train", "/study")


@router.get("/visits", summary="访问量统计")
async def visit_stats(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
    days: int = 7,
):
    """今日 / 昨日 / 近 N 天 / 累计，附各页面分布与逐日曲线。"""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    window_start = today_start - timedelta(days=days - 1)

    def count_since(start: datetime) -> int:
        return db.query(func.count(PageVisit.id)).filter(
            PageVisit.created_at >= start).scalar() or 0

    today = count_since(today_start)
    yesterday = db.query(func.count(PageVisit.id)).filter(
        PageVisit.created_at >= yesterday_start,
        PageVisit.created_at < today_start).scalar() or 0
    week = count_since(window_start)
    total = db.query(func.count(PageVisit.id)).scalar() or 0

    # 各页面累计
    by_page = {
        path: db.query(func.count(PageVisit.id)).filter(PageVisit.path == path).scalar() or 0
        for path in TRACKED_PAGES
    }

    # 逐日曲线
    daily = []
    for offset in range(days - 1, -1, -1):
        day_start = today_start - timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        n = db.query(func.count(PageVisit.id)).filter(
            PageVisit.created_at >= day_start,
            PageVisit.created_at < day_end).scalar() or 0
        daily.append({"date": day_start.strftime("%m-%d"), "count": n})

    return {
        "today": today,
        "yesterday": yesterday,
        "week": week,
        "total": total,
        "by_page": by_page,
        "daily": daily,
    }
