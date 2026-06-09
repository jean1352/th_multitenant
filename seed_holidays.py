import asyncio
import json
import os
import asyncpg
from datetime import datetime
from dotenv import load_dotenv

async def seed_holidays():
    load_dotenv()
    
    user = os.getenv("POSTGRES_USER", "admin")
    password = os.getenv("POSTGRES_PASSWORD", "W0gR540SOjaL")
    database = os.getenv("POSTGRES_DB", "talento_up_db")
    host = os.getenv("POSTGRES_SERVER", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    
    print(f"Connecting to {host}:{port}/{database} as {user} to seed holidays...")
    
    try:
        conn = await asyncpg.connect(
            user=user, 
            password=password, 
            database=database, 
            host=host, 
            port=port
        )
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return

    # Load holidays from JSON
    json_path = "dias_no_laborales.json"
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        await conn.close()
        return

    with open(json_path, "r", encoding="utf-8") as f:
        holiday_data = json.load(f)

    holidays = holiday_data.get("data", {}).get("data", [])
    print(f"Loaded {len(holidays)} holidays from JSON.")

    async def seed_schema(schema_name: str):
        print(f"\n--- Seeding holidays in schema: '{schema_name}' ---")
        
        # Set search path to this schema
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        # 1. Ensure "Feriado" event type exists
        event_type = await conn.fetchrow(
            "SELECT id FROM calendar_event_types WHERE name = $1", "Feriado"
        )
        if not event_type:
            event_type_id = await conn.fetchval(
                """
                INSERT INTO calendar_event_types (name, color, affects_sla, description)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                "Feriado", "#EF4444", True, "Feriados nacionales y días no laborales que afectan al cálculo de SLA"
            )
            print(f"Created event type 'Feriado' with ID: {event_type_id}")
        else:
            event_type_id = event_type["id"]
            print(f"Found existing event type 'Feriado' with ID: {event_type_id}")

        # 2. Seed holidays
        inserted = 0
        skipped = 0
        for h in holidays:
            nombre = h.get("nombre")
            fecha_str = h.get("fecha")
            if not nombre or not fecha_str:
                continue

            # Convert to date object
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()

            # Check if event already exists on this date in this schema
            existing = await conn.fetchrow(
                "SELECT id FROM calendar_events WHERE date = $1 AND event_type_id = $2",
                fecha, event_type_id
            )

            if not existing:
                await conn.execute(
                    """
                    INSERT INTO calendar_events (title, description, date, event_type_id, is_enrollable)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    nombre, f"Feriado: {nombre}", fecha, event_type_id, False
                )
                inserted += 1
            else:
                skipped += 1

        print(f"Finished seeding '{schema_name}': {inserted} inserted, {skipped} skipped.")

    try:
        # Seed the public schema first
        await seed_schema("public")

        # Now, fetch all tenants and seed their schemas as well
        tenants = await conn.fetch("SELECT subdomain, schema_name FROM public.tenants")
        print(f"\nFound {len(tenants)} tenants in the system.")
        
        for t in tenants:
            schema_name = t["schema_name"]
            # Verify if schema exists in PostgreSQL
            schema_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = $1)", schema_name
            )
            if schema_exists:
                await seed_schema(schema_name)
            else:
                print(f"Warning: Tenant schema '{schema_name}' does not exist in PostgreSQL. Skipping.")

    except Exception as e:
        print(f"An error occurred during holiday seeding: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(seed_holidays())
