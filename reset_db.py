import asyncio
import logging
from sqlalchemy import text
from app.core.database import engine, Base

# IMPORTAR TODOS LOS MODELOS (CRÍTICO PARA CREATE_ALL)
import app.modules.auth.models
import app.modules.organization.models
import app.modules.recruitment.models
import app.modules.employees.models
import app.modules.trainings.models
import app.modules.notifications.models
import app.modules.calendar.models
import app.modules.benefits.models
import app.modules.disciplinary.models
import app.modules.dietary.models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def reset_database():
    logger.warning("☢️  INICIANDO RESET NUCLEAR DE LA BASE DE DATOS...")
    
    async with engine.begin() as conn:
        logger.info("🔥 Borrando esquema public (DROP SCHEMA CASCADE)...")
        await conn.execute(text("DROP SCHEMA public CASCADE;"))
        
        logger.info("✨ Recreando esquema public...")
        await conn.execute(text("CREATE SCHEMA public;"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
        
        logger.info("✅ Base de datos limpia.")

        logger.info("🏗️  Creando tablas nuevas...")
        await conn.run_sync(Base.metadata.create_all)
        
        logger.info("🚀 ¡SISTEMA REINICIADO EXITOSAMENTE!")

if __name__ == "__main__":
    asyncio.run(reset_database())