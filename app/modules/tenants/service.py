from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.modules.tenants.models import Tenant
from app.core.database import Base, engine
import logging

logger = logging.getLogger(__name__)

async def create_tenant(db: AsyncSession, name: str, subdomain: str) -> Tenant:
    """
    Crea un nuevo tenant, su esquema en la base de datos y todas las tablas necesarias.
    """
    schema_name = f"tenant_{subdomain.replace('-', '_')}"
    
    # 1. Crear el registro en la tabla pública
    new_tenant = Tenant(
        name=name,
        subdomain=subdomain,
        schema_name=schema_name
    )
    db.add(new_tenant)
    await db.commit()
    await db.refresh(new_tenant)
    
    # 2. Crear el esquema en PostgreSQL
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        
        # 3. Crear las tablas en el nuevo esquema
        # Para esto, temporalmente seteamos el search_path en la conexión de creación
        await conn.execute(text(f'SET search_path TO "{schema_name}"'))
        
        # Ejecutamos create_all para el esquema actual
        # Base.metadata.create_all es síncrono, necesitamos run_sync
        await conn.run_sync(Base.metadata.create_all)
        
    logger.info(f"Tenant '{name}' creado con esquema '{schema_name}'")
    return new_tenant

async def get_tenant_by_subdomain(db: AsyncSession, subdomain: str) -> Tenant:
    from sqlalchemy import select
    result = await db.execute(select(Tenant).where(Tenant.subdomain == subdomain))
    return result.scalar_one_or_none()
