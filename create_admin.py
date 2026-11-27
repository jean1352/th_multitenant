import asyncio
import logging
import sys
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. CONFIGURACIÓN DB
from app.core.database import AsyncSessionLocal, engine, Base

# 2. IMPORTAR TODOS LOS MODELOS (CRÍTICO: El orden no importa tanto, pero deben estar TODOS)
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

# 3. IMPORTAR MODELO ESPECÍFICO Y UTILS
from app.modules.auth.models import User, UserRole
from app.core.security import get_password_hash

async def create_super_user():
    logger.info("--- INICIANDO SCRIPT DE ADMINISTRADOR ---")
    
    # PASO 0: Asegurar que las tablas existen (Idempotente)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    retries = 5
    session = None
    
    for i in range(retries):
        try:
            session = AsyncSessionLocal()
            await session.execute(select(1))
            break
        except OperationalError:
            logger.warning(f"Base de datos no lista, reintentando ({i+1}/{retries})...")
            await asyncio.sleep(2)
            if session: await session.close()
            if i == retries - 1: sys.exit(1)

    try:
        email = "admin@upacifico.edu.py"
        password = "admin123"
        
        logger.info(f"Verificando existencia de {email}...")
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            logger.warning(f"AVISO: El usuario {email} ya existe.")
            return

        logger.info("Creando usuario...")
        hashed_pwd = get_password_hash(password)
        
        new_admin = User(
            email=email,
            full_name="Administrador Sistema",
            hashed_password=hashed_pwd,
            role=UserRole.ADMIN,
            is_active=True,
            sede_id=None,
            area_id=None
        )
        
        session.add(new_admin)
        await session.commit()
        
        logger.info("✅ ÉXITO: Usuario Administrador creado correctamente.")
        
    except Exception as e:
        logger.error(f"❌ ERROR CRÍTICO: {e}")
        await session.rollback()
    finally:
        if session: await session.close()

if __name__ == "__main__":
    asyncio.run(create_super_user())