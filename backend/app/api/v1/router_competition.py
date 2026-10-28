"""R4-only competition evidence API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_roles
from app.core.exceptions import ok
from app.db.session import get_db
from app.services.competition.evidence import build_competition_evidence

router = APIRouter(prefix="/competition", tags=["competition"])


@router.get("/evidence", response_model=None)
async def evidence(_: object = Depends(require_roles("R4")), db: AsyncSession = Depends(get_db)):
    return ok(await build_competition_evidence(db))
