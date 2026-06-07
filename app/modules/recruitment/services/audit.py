from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.recruitment.models import RecruitmentAudit

async def log_audit(
    db: AsyncSession, 
    vacancy_id: int, 
    action: str, 
    details: str, 
    user_id: Optional[int] = None
):
    """Registra una acción en la tabla de auditoría."""
    audit = RecruitmentAudit(
        vacancy_id=vacancy_id,
        user_id=user_id,
        action=action,
        details=details
    )
    db.add(audit)
    # No hacemos commit aquí para que sea parte de la transacción principal del llamador