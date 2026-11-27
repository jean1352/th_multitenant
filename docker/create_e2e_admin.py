"""Prepara el administrador E2E con las credenciales de la ejecución."""

import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Registrar todos los modelos para resolver las relaciones de User.
import main  # noqa: F401, E402
from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.core.security import get_password_hash, verify_password  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.auth.schemas import UserCreate  # noqa: E402


async def prepare_admin() -> None:
    if settings.POSTGRES_DB != "talento_up_test":
        raise RuntimeError("El administrador E2E solo puede prepararse en talento_up_test.")

    email = os.environ.get("E2E_ADMIN_EMAIL", "").strip()
    password = os.environ.get("E2E_ADMIN_PASSWORD", "")
    if not email or not password.strip():
        raise RuntimeError("Se requieren E2E_ADMIN_EMAIL y E2E_ADMIN_PASSWORD.")
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise RuntimeError("E2E_ADMIN_PASSWORD debe tener al menos 12 caracteres y como máximo 72 bytes.")

    data = UserCreate(
        email=email,
        password=password,
        full_name="Administrador E2E",
        role=UserRole.ADMIN,
        is_active=True,
    )
    try:
        async with AsyncSessionLocal.begin() as db:
            user = await db.scalar(select(User).where(User.email == data.email))
            if user:
                if user.role != UserRole.ADMIN:
                    raise RuntimeError("El correo E2E configurado pertenece a una cuenta sin rol de administrador.")
                if not verify_password(data.password, user.hashed_password):
                    user.hashed_password = get_password_hash(data.password)
                user.is_active = True
            else:
                db.add(User(
                    **data.model_dump(exclude={"password"}),
                    hashed_password=get_password_hash(data.password),
                ))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(prepare_admin())
    print("Administrador E2E preparado con las credenciales de la ejecución.")
