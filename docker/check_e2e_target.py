"""Comprueba la conexión de web-test antes de que los fixtures creen datos."""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.core.config import Settings, settings  # noqa: E402
from app.core.database import engine  # noqa: E402


EXAMPLE_SECRET_KEYS = {
    "cambiar_esta_clave_exclusiva_para_e2e",
    "cambiar_esto_por_una_cadena_larga_y_aleatoria_insegura_para_dev",
    "cambiar_esto_por_una_clave_segura_en_produccion",
    Settings.model_fields["SECRET_KEY"].default,
}


async def check_target() -> None:
    if settings.POSTGRES_DB != "talento_up_test":
        raise RuntimeError("web-test debe estar configurado con POSTGRES_DB=talento_up_test.")

    secret_key = settings.SECRET_KEY.strip()
    if not secret_key or secret_key in EXAMPLE_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY de E2E no puede estar vacía ni usar un valor de ejemplo. "
            "Genera una clave con 'openssl rand -hex 32', guárdala en .env.test "
            "y vuelve a iniciar web-test con 'npm run env:e2e:up'."
        )

    try:
        async with engine.connect() as connection:
            database = await connection.scalar(text("SELECT current_database()"))
            if database != "talento_up_test":
                raise RuntimeError("La conexión de web-test no corresponde a talento_up_test.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_target())
