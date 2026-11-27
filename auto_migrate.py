import os
import sys
import asyncio
from datetime import datetime
from sqlalchemy import text, inspect
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql
from app.core.database import engine, Base

# --- IMPORTAR TODOS LOS MODELOS ---
import app.modules.auth.models
import app.modules.organization.models
import app.modules.recruitment.models
import app.modules.employees.models
import app.modules.trainings.models
import app.modules.notifications.models
import app.modules.calendar.models
import app.modules.scheduler.models
import app.modules.benefits.models

MIGRATION_DIR = "sql_versions"
VERSION_TABLE = "schema_version"
EOS_MARKER = "--__EOS__"  # Separador seguro de sentencias

def get_column_type_sql(column):
    """Obtiene solo la definición del tipo de dato SQL."""
    type_sql = column.type.compile(dialect=postgresql.dialect())
    if str(type_sql) == 'VARCHAR':
        return 'VARCHAR' 
    return str(type_sql)

def get_enum_creation_sql(column):
    """Genera el SQL seguro para crear un ENUM si no existe."""
    if hasattr(column.type, 'enums'):
        type_name = column.type.name 
        enums = "', '".join(e.replace("'", "''") for e in column.type.enums)
        return f"""
DO $$ BEGIN
    CREATE TYPE {type_name} AS ENUM ('{enums}');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
"""
    return ""

async def analyze_and_generate():
    print("🔍 Analizando Modelos vs Base de Datos...")
    
    sqls = []
    
    async with engine.connect() as conn:
        def inspect_db(connection):
            inspector = inspect(connection)
            existing_tables = inspector.get_table_names()
            
            local_sqls = []
            
            for table_name, table in Base.metadata.tables.items():
                print(f"DEBUG: Checking table {table_name}")
                if table_name not in existing_tables:
                    print(f"  ➕ Tabla nueva: {table_name}")
                    create_stmt = CreateTable(table).compile(dialect=postgresql.dialect())
                    local_sqls.append(str(create_stmt) + ";")
                else:
                    existing_columns = [c['name'] for c in inspector.get_columns(table_name)]
                    for column in table.columns:
                        if column.name not in existing_columns:
                            print(f"  ➕ Columna nueva: {table_name}.{column.name}")
                            
                            enum_sql = get_enum_creation_sql(column)
                            if enum_sql:
                                local_sqls.append(enum_sql)
                            
                            col_type = get_column_type_sql(column)
                            
                            if not column.nullable and column.server_default is None:
                                if hasattr(column.type, 'enums'):
                                    default_val = f"'{column.type.enums[0]}'::{column.type.name}"
                                    local_sqls.append(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type} DEFAULT {default_val} NOT NULL;")
                                else:
                                    local_sqls.append(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type} NOT NULL;")
                            else:
                                local_sqls.append(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type};")

            return local_sqls

        sqls = await conn.run_sync(inspect_db)

    if not sqls:
        print("✅ No se detectaron cambios estructurales.")
        return None

    if not os.path.exists(MIGRATION_DIR):
        os.makedirs(MIGRATION_DIR)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_auto_migration.sql"
    filepath = os.path.join(MIGRATION_DIR, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("-- Migración generada automáticamente\n")
        # Unimos usando el marcador para poder separar después
        f.write(f"\n{EOS_MARKER}\n".join(sqls))
    
    print(f"\n📝 Archivo generado: {filepath}")
    return filename

async def apply_migrations():
    print("\n🚀 Ejecutando migraciones pendientes...")
    
    async with engine.begin() as conn:
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT NOW()
            );
        """))
        
        if not os.path.exists(MIGRATION_DIR):
            print("No hay directorio de migraciones.")
            return

        files = sorted([f for f in os.listdir(MIGRATION_DIR) if f.endswith(".sql")])
        
        for filename in files:
            res = await conn.execute(text(f"SELECT 1 FROM {VERSION_TABLE} WHERE version = :v"), {"v": filename})
            if res.scalar():
                continue
            
            print(f"⚡ Aplicando: {filename}...")
            with open(os.path.join(MIGRATION_DIR, filename), "r") as f:
                content = f.read()
            
            # SEPARAR COMANDOS USANDO EL MARCADOR
            commands = content.split(EOS_MARKER)
            
            for cmd in commands:
                if cmd.strip():
                    # Limpiar comentarios iniciales si quedaron pegados
                    clean_cmd = cmd.replace("-- Migración generada automáticamente", "").strip()
                    if clean_cmd:
                        try:
                            await conn.execute(text(clean_cmd))
                        except Exception as e:
                            print(f"❌ Error en comando:\n{clean_cmd}\nError: {e}")
                            raise e

            await conn.execute(text(f"INSERT INTO {VERSION_TABLE} (version) VALUES (:v)"), {"v": filename})
            print(f"✅ Hecho.")

    # Sincronizar valores de ENUMs nativos (ALTER TYPE ... ADD VALUE) después de
    # aplicar las migraciones estructurales.
    await sync_enum_values()


async def sync_enum_values():
    """Agrega valores faltantes a los ENUMs nativos de PostgreSQL.

    `Base.metadata.create_all()` NO altera enums existentes, por lo que cuando se
    agrega un miembro nuevo a un enum de Python hay que reflejarlo en la BD con
    `ALTER TYPE ... ADD VALUE`. Ese comando no puede ejecutarse dentro de una
    transacción, por lo que se usa AUTOCOMMIT (y se reasigna la conexión, porque
    `execution_options()` devuelve una conexión nueva).
    """
    print("\n🔧 Sincronizando valores de ENUMs nativos de PostgreSQL...")

    async with engine.connect() as conn:
        # execution_options() devuelve una NUEVA conexión; hay que reasignarla.
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")

        for table in Base.metadata.tables.values():
            for column in table.columns:
                if not hasattr(column.type, "enums") or not column.type.enums:
                    continue
                type_name = getattr(column.type, "name", None)
                if not type_name:
                    continue
                for val in column.type.enums:
                    safe_val = str(val).replace("'", "''")
                    try:
                        await conn.execute(
                            text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{safe_val}'")
                        )
                        print(f"  ✅ {type_name}: '{val}'")
                    except Exception as e:
                        # Si el tipo aún no existe (tabla nueva), lo creará
                        # create_all / CreateTable con todos sus valores.
                        print(f"  ⚠️  {type_name}: '{val}' -> {e}")

    print("✅ Sincronización de ENUMs finalizada.\n")


async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "apply":
        await apply_migrations()
    else:
        new_file = await analyze_and_generate()
        if new_file:
            resp = input("\n¿Deseas aplicar estos cambios ahora? [S/n]: ").lower()
            if resp in ["", "s", "si", "y"]:
                await apply_migrations()

if __name__ == "__main__":
    asyncio.run(main())