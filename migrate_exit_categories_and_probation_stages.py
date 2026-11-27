import asyncio
import logging
from sqlalchemy import text
from app.core.database import engine

# Importar todos los modelos para configurar el registro de clases de SQLAlchemy
import app.modules.auth.models
import app.modules.organization.models
import app.modules.recruitment.models
import app.modules.employees.models
import app.modules.trainings.models
import app.modules.notifications.models
import app.modules.calendar.models
import app.modules.scheduler.models
import app.modules.benefits.models
import app.modules.disciplinary.models
import app.modules.dietary.models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sentencias idempotentes: las tablas nuevas las crea `Base.metadata.create_all`
# al arrancar, pero las incluimos con IF NOT EXISTS por robustez. La columna sobre
# una tabla existente NO la agrega create_all, por eso va explícita aquí.
STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS exit_categories (
        id SERIAL PRIMARY KEY,
        name VARCHAR NOT NULL UNIQUE,
        description TEXT,
        is_active BOOLEAN DEFAULT TRUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS probation_stages (
        id SERIAL PRIMARY KEY,
        probation_duration_id INTEGER NOT NULL REFERENCES probation_durations(id) ON DELETE CASCADE,
        name VARCHAR NOT NULL,
        days INTEGER NOT NULL,
        description TEXT,
        sort_order INTEGER DEFAULT 0 NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS employee_probation_stages (
        id SERIAL PRIMARY KEY,
        employee_position_id INTEGER NOT NULL REFERENCES employee_positions(id) ON DELETE CASCADE,
        name VARCHAR NOT NULL,
        days INTEGER NOT NULL,
        description TEXT,
        due_date DATE,
        sort_order INTEGER DEFAULT 0 NOT NULL,
        is_completed BOOLEAN DEFAULT FALSE NOT NULL,
        completed_at DATE
    )
    """,
    """
    ALTER TABLE employee_history
        ADD COLUMN IF NOT EXISTS exit_category_id INTEGER REFERENCES exit_categories(id)
    """,
    """
    INSERT INTO exit_categories (name, description, is_active) VALUES
        ('Despido dentro del PP', NULL, TRUE),
        ('Renuncia dentro del PP', NULL, TRUE),
        ('Despido', NULL, TRUE),
        ('Renuncia', NULL, TRUE),
        ('Terminación de contrato', NULL, TRUE)
    ON CONFLICT (name) DO NOTHING
    """,
]


async def migrate():
    logger.info("Aplicando migración: categorías de salida y etapas de periodo de prueba...")
    async with engine.begin() as conn:
        for statement in STATEMENTS:
            await conn.execute(text(statement))
    logger.info("Migración aplicada correctamente.")


if __name__ == "__main__":
    asyncio.run(migrate())
