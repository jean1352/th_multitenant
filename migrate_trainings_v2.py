import asyncio
import logging
from sqlalchemy import text
from app.core.database import engine, Base
from auto_migrate import sync_enum_values

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

ALTER_STATEMENTS = [
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS code VARCHAR",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS objective TEXT",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS modality VARCHAR DEFAULT 'presencial'",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS topic_id INTEGER REFERENCES training_topics(id)",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS topic VARCHAR",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS cost DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS currency_id INTEGER REFERENCES currencies(id)",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS currency VARCHAR",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS cost_center_id INTEGER REFERENCES cost_centers(id)",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS hours DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS capacity INTEGER",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS sede_id INTEGER REFERENCES sedes(id)",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS location VARCHAR",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS meeting_url VARCHAR",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS requires_manager_approval BOOLEAN DEFAULT FALSE",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS min_passing_score DOUBLE PRECISION",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS min_attendance_pct DOUBLE PRECISION",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS source_training_id INTEGER REFERENCES trainings(id)",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS target_area_id INTEGER REFERENCES areas(id)",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users(id)",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS enrolled_at TIMESTAMPTZ DEFAULT NOW()",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS waitlist_position INTEGER",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS attendance_pct DOUBLE PRECISION",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS result VARCHAR",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS certificate_file VARCHAR",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS approved_by_user_id INTEGER REFERENCES users(id)",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
    "ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ",
    "ALTER TABLE training_sessions ADD COLUMN IF NOT EXISTS qr_code_token VARCHAR",
    "ALTER TABLE training_sessions ADD COLUMN IF NOT EXISTS location_or_link VARCHAR",
    "ALTER TABLE training_sessions ADD COLUMN IF NOT EXISTS meeting_platform VARCHAR",
    "ALTER TABLE training_attendances ADD COLUMN IF NOT EXISTS attendance_status VARCHAR DEFAULT 'absent'",
    "ALTER TABLE training_attendances ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ",
    "ALTER TABLE training_attendances ADD COLUMN IF NOT EXISTS method VARCHAR DEFAULT 'manual'",
    "ALTER TABLE training_attendances ADD COLUMN IF NOT EXISTS recorded_by_user_id INTEGER REFERENCES users(id)",
]


async def migrate():
    logger.info("Aplicando migración idempotente del Módulo de Capacitaciones...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in ALTER_STATEMENTS:
            await conn.execute(text(stmt))
    await sync_enum_values()
    logger.info("Migración de Capacitaciones aplicada correctamente.")


if __name__ == "__main__":
    asyncio.run(migrate())
