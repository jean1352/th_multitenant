"""Elimina los datos creados por un fixture de vacante, sin vaciar la base."""

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Registrar todos los modelos, igual que al iniciar el backend.
import main  # noqa: F401, E402
from sqlalchemy import delete, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.modules.auth.models import User  # noqa: E402
from app.modules.organization.models import Area, Position, Sede  # noqa: E402
from app.modules.recruitment.models import (  # noqa: E402
    HiringReason,
    ProcessStage,
    RecruitmentAudit,
    RecruitmentProcess,
    Vacancy,
    VacancyStage,
)


async def cleanup(ids: dict[str, int]) -> None:
    if settings.POSTGRES_DB != "talento_up_test":
        raise RuntimeError("La limpieza E2E solo puede ejecutarse en talento_up_test.")

    # Orden de borrado según las claves foráneas, después de vacantes y etapas.
    # Usuarios y cargos dependen del área; el área depende de la sede.
    recursos_en_orden = [
        ("proceso", RecruitmentProcess),
        ("responsable", User),
        ("cargo", Position),
        ("area", Area),
        ("sede", Sede),
        ("motivo", HiringReason),
    ]
    recursos_permitidos = {nombre for nombre, _ in recursos_en_orden}
    if any(key not in recursos_permitidos or type(value) is not int or value <= 0
           for key, value in ids.items()):
        raise ValueError("Se requieren IDs positivos de recursos del fixture.")

    try:
        async with AsyncSessionLocal.begin() as db:
            if proceso_id := ids.get("proceso"):
                vacantes = select(Vacancy.id).where(Vacancy.process_id == proceso_id)
                await db.execute(delete(RecruitmentAudit).where(RecruitmentAudit.vacancy_id.in_(vacantes)))
                await db.execute(delete(VacancyStage).where(VacancyStage.vacancy_id.in_(vacantes)))
                await db.execute(delete(Vacancy).where(Vacancy.process_id == proceso_id))
                await db.execute(delete(ProcessStage).where(ProcessStage.process_id == proceso_id))

            # Respetar las dependencias; el fixture admin limpia la cuenta de login.
            for nombre, modelo in recursos_en_orden:
                if recurso_id := ids.get(nombre):
                    await db.execute(delete(modelo).where(modelo.id == recurso_id))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(cleanup(json.loads(sys.argv[1])))
