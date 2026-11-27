"""Elimina únicamente la cuenta temporal de una prueba E2E."""

import asyncio
from pathlib import Path
import re
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Registrar todos los modelos para resolver las relaciones de User.
import main  # noqa: F401, E402
from pydantic import EmailStr, TypeAdapter  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402


async def cleanup_admin(email: str) -> None:
    if settings.POSTGRES_DB != "talento_up_test":
        raise RuntimeError("La limpieza del administrador E2E solo puede ejecutarse en talento_up_test.")

    # Normalizar igual que UserCreate antes de buscar la cuenta guardada.
    email = TypeAdapter(EmailStr).validate_python(email)
    match = re.fullmatch(r"[^@]+\+e2e-w[0-9]+-([0-9a-f-]{36})@[^@]+", email)
    if not match or str(UUID(match[1])) != match[1]:
        raise ValueError("Solo se pueden eliminar cuentas temporales generadas por el fixture E2E.")

    try:
        async with AsyncSessionLocal.begin() as db:
            user = await db.scalar(select(User).where(User.email == email))
            if user:
                if user.role != UserRole.ADMIN or user.full_name != "Administrador E2E":
                    raise RuntimeError("La cuenta indicada no corresponde a un administrador temporal E2E.")
                await db.delete(user)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(cleanup_admin(sys.argv[1]))
