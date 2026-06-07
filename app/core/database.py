import sys
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.core.config import settings

# Debugging: Imprimir URL de conexión (Ocultando password)
try:
    safe_url = settings.SQLALCHEMY_DATABASE_URI.split("@")[-1]
    print(f"--- CONECTANDO A DB: postgresql+asyncpg://****@{safe_url} ---")
except Exception:
    print("--- ERROR GENERANDO URL DE DB ---")

# Motor Asíncrono
try:
    engine = create_async_engine(
        settings.SQLALCHEMY_DATABASE_URI,
        echo=False,
        future=True,
        # Desactivamos el cache de statements preparados para evitar errores 
        # al cambiar dinámicamente el search_path (multi-tenancy).
        connect_args={
            "prepared_statement_cache_size": 0
        }
    )
except Exception as e:
    print(f"FATAL: Error creando motor de base de datos: {e}")
    sys.exit(1)

# Factory de Sesiones
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    pass

# Dependencia para FastAPI
async def get_db():
    from app.core.tenants import get_current_tenant
    async with AsyncSessionLocal() as session:
        tenant = get_current_tenant()
        if tenant:
            # Seteamos el search_path para que las consultas se dirijan al esquema del tenant
            # Incluimos 'public' al final para que las tablas globales (como 'tenants') sigan siendo accesibles
            await session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
        try:
            yield session
        finally:
            await session.close()
