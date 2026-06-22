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
        else:
            # Si no hay tenant, nos aseguramos de que la conexión use el esquema público
            await session.execute(text('SET search_path TO public'))
        try:
            yield session
        finally:
            await session.close()


async def auto_upgrade_db_schema():
    """
    Sincroniza automáticamente la base de datos con los modelos de SQLAlchemy.
    Crea las tablas faltantes y añade nuevas columnas en esquemas globales y de tenants
    sin alterar los datos existentes.
    """
    from sqlalchemy import inspect, select
    
    print("🚀 Iniciando migración automática del esquema de base de datos...")
    
    # 1. Función síncrona que verifica y añade columnas faltantes en un esquema dado
    def sync_schema_columns(connection, schema_name: str):
        inspector = inspect(connection)
        
        # Obtener las tablas existentes en este esquema
        existing_tables = inspector.get_table_names(schema=schema_name)
        if not existing_tables:
            return
            
        for table_name, table in Base.metadata.tables.items():
            model_schema = table.schema or "public"
            
            # Si estamos migrando un tenant independiente, ignoramos las tablas globales que
            # pertenecen estrictamente al esquema público (como 'tenants').
            if schema_name != "public" and model_schema == "public" and table_name == "tenants":
                continue
                
            if table_name not in existing_tables:
                continue
                
            # Obtener columnas existentes en la tabla del esquema correspondiente
            columns_info = inspector.get_columns(table_name, schema=schema_name)
            existing_cols = {col['name'] for col in columns_info}
            
            for col_name, column in table.columns.items():
                if col_name not in existing_cols:
                    try:
                        col_type = column.type.compile(dialect=connection.dialect)
                        # Armar la sentencia ALTER TABLE segura para el esquema correspondiente
                        alter_query = f'ALTER TABLE "{schema_name}"."{table_name}" ADD COLUMN "{col_name}" {col_type}'
                        
                        # Manejo de claves foráneas
                        if column.foreign_keys:
                            for fk in column.foreign_keys:
                                fk_table_schema = fk.column.table.schema or "public"
                                if schema_name != "public" and fk_table_schema != "public":
                                    alter_query += f' REFERENCES "{schema_name}"."{fk.column.table.name}"("{fk.column.name}")'
                                else:
                                    alter_query += f' REFERENCES "{fk_table_schema}"."{fk.column.table.name}"("{fk.column.name}")'
                                    
                        connection.execute(text(alter_query))
                        print(f"✅ [Auto-Migration] {schema_name}.{table_name}: Añadida columna '{col_name}'")
                    except Exception as e:
                        print(f"❌ [Auto-Migration] Error agregando {schema_name}.{table_name}.{col_name}: {e}")

    # --- PASO 1: Sincronizar el Esquema Público (Global) ---
    async with engine.begin() as conn:
        print("🌍 Sincronizando esquema público (global)...")
        # Aseguramos que todas las tablas globales existan
        await conn.run_sync(Base.metadata.create_all)
        # Sincronizamos las columnas de 'public'
        await conn.run_sync(lambda connection: sync_schema_columns(connection, "public"))

    # --- PASO 2: Cargar todos los Tenants registrados ---
    tenant_schemas = []
    try:
        from app.modules.tenants.models import Tenant
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Tenant.schema_name))
            tenant_schemas = [row[0] for row in result.all()]
    except Exception as e:
        print(f"⚠️ No se pudieron cargar los tenants (normal si es la primera instalación): {e}")

    # --- PASO 3: Sincronizar cada Tenant ---
    for schema in tenant_schemas:
        print(f"🏢 Sincronizando esquema de tenant: '{schema}'...")
        async with engine.begin() as conn:
            # Apuntar temporalmente al esquema del tenant para create_all y alter table
            await conn.execute(text(f'SET search_path TO "{schema}", public'))
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(lambda connection: sync_schema_columns(connection, schema))
            # Restablecer el search_path
            await conn.execute(text('SET search_path TO public'))
            
    print("🚀 Sincronización automática de base de datos finalizada correctamente.")

