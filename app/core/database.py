import sys
from contextlib import asynccontextmanager
from typing import Optional
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


@asynccontextmanager
async def get_tenant_db(schema_name: Optional[str] = None):
    """Sesión asíncrona aislada al esquema del tenant (para BackgroundTasks y Scheduler)."""
    from app.core.tenants import get_current_tenant
    if schema_name is None:
        tenant = get_current_tenant()
        schema_name = tenant.schema_name if tenant else None
    async with AsyncSessionLocal() as session:
        if schema_name:
            await session.execute(text(f'SET search_path TO "{schema_name}", public'))
        else:
            await session.execute(text('SET search_path TO public'))
        try:
            yield session
        finally:
            await session.close()


def tenant_db_factory():
    """Captura el esquema del tenant actual y devuelve una factory de sesiones para BackgroundTasks."""
    from app.core.tenants import get_current_tenant
    tenant = get_current_tenant()
    schema_name = tenant.schema_name if tenant else None
    return lambda: get_tenant_db(schema_name)


def sync_enum_values_for_schema(connection, schema_name: str):
    """Agrega valores faltantes a los ENUMs nativos de PostgreSQL del esquema dado.

    `Base.metadata.create_all()` no altera enums existentes, así que cuando se
    agrega un miembro nuevo a un enum de Python hay que reflejarlo en la BD con
    `ALTER TYPE ... ADD VALUE IF NOT EXISTS` dentro de un SAVEPOINT (`begin_nested`)
    para que ningún error puntual aborte la transacción de migración.
    """
    connection.execute(text(f'SET search_path TO "{schema_name}"'))
    seen_types = set()
    for table in Base.metadata.tables.values():
        model_schema = table.schema or "public"
        if schema_name != "public" and model_schema == "public" and table.name == "tenants":
            continue
        for column in table.columns:
            col_type = column.type
            if not hasattr(col_type, "enums") or not col_type.enums:
                continue
            type_name = getattr(col_type, "name", None)
            if not type_name or type_name in seen_types:
                continue
            seen_types.add(type_name)

            # Verificar que el tipo ENUM exista realmente en este esquema
            exists = connection.execute(
                text(
                    "SELECT 1 FROM pg_type t "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE t.typname = :tname AND n.nspname = :sname"
                ),
                {"tname": type_name, "sname": schema_name},
            ).scalar()
            if not exists:
                continue

            for val in col_type.enums:
                safe_val = str(val).replace("'", "''")
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(f'ALTER TYPE "{schema_name}"."{type_name}" ADD VALUE IF NOT EXISTS \'{safe_val}\'')
                        )
                except Exception as e:
                    print(f"  ⚠️ [Enum] {schema_name}.{type_name}: '{val}' -> {e}")

    if schema_name != "public":
        connection.execute(text(f'SET search_path TO "{schema_name}", public'))
    else:
        connection.execute(text('SET search_path TO public'))


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

    # 2. Función síncrona para migrar la nulidad y tipos VARCHAR en automation_rules / automation_states
    def migrate_automation_rules_nullability(connection, schema_name: str):
        inspector = inspect(connection)
        existing_tables = inspector.get_table_names(schema=schema_name)
        if "automation_rules" in existing_tables:
            try:
                with connection.begin_nested():
                    connection.execute(text(f'ALTER TABLE "{schema_name}"."automation_rules" ALTER COLUMN "rule_type" DROP NOT NULL'))
                print(f"✅ [Auto-Migration] {schema_name}.automation_rules: Removido constraint NOT NULL en 'rule_type'")
            except Exception as e:
                print(f"⚠️ [Auto-Migration] No se pudo alterar 'rule_type' en {schema_name}: {e}")

        # Alinear columnas enum de scheduler con native_enum=False (VARCHAR) en modelos
        for tbl, col in [
            ("automation_rules", "rule_type"),
            ("automation_rules", "frequency"),
            ("automation_rules", "trigger_type"),
            ("automation_states", "status"),
        ]:
            if tbl not in existing_tables:
                continue
            dt = connection.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
                ),
                {"s": schema_name, "t": tbl, "c": col},
            ).scalar()
            if dt == "USER-DEFINED":
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(f'ALTER TABLE "{schema_name}"."{tbl}" ALTER COLUMN "{col}" TYPE VARCHAR USING "{col}"::text')
                        )
                    print(f"✅ [Auto-Migration] {schema_name}.{tbl}.{col}: Convertido ENUM a VARCHAR")
                except Exception as e:
                    print(f"⚠️ [Auto-Migration] Error convirtiendo {schema_name}.{tbl}.{col} a VARCHAR: {e}")

    # --- PASO 1: Sincronizar el Esquema Público (Global) ---
    async with engine.begin() as conn:
        print("🌍 Sincronizando esquema público (global)...")
        # Aseguramos que todas las tablas globales existan
        await conn.run_sync(Base.metadata.create_all)
        # Sincronizamos los valores de los ENUMs nativos
        await conn.run_sync(lambda connection: sync_enum_values_for_schema(connection, "public"))
        # Sincronizamos las columnas de 'public'
        await conn.run_sync(lambda connection: sync_schema_columns(connection, "public"))
        # Aseguramos la nulidad del rule_type
        await conn.run_sync(lambda connection: migrate_automation_rules_nullability(connection, "public"))

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
            # Apuntar temporalmente al esquema del tenant únicamente para create_all,
            # evitando que detecte las tablas en public y omita crearlas aquí.
            await conn.execute(text(f'SET search_path TO "{schema}"'))
            await conn.run_sync(Base.metadata.create_all)
            
            # Ahora agregamos 'public' al search_path para poder sincronizar columnas/claves foráneas con public
            await conn.execute(text(f'SET search_path TO "{schema}", public'))
            await conn.run_sync(lambda connection: sync_enum_values_for_schema(connection, schema))
            await conn.run_sync(lambda connection: sync_schema_columns(connection, schema))
            await conn.run_sync(lambda connection: migrate_automation_rules_nullability(connection, schema))
            
            # Restablecer el search_path
            await conn.execute(text('SET search_path TO public'))
            
    print("🚀 Sincronización automática de base de datos finalizada correctamente.")

