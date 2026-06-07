#bin/bash

# 1. Reiniciar contenedores para asegurar limpieza de memoria/cache
docker compose down
docker compose build --no-cache
docker compose up -d

echo "⏳ Esperando a que la base de datos inicie..."
sleep 5

# 2. Resetear Base de Datos (Drop & Create Tables)
docker compose exec web python reset_db.py

# 3. Crear Super Usuario
docker compose exec web python create_admin.py

# 4. Cargar Datos Estructurales (Sedes, Áreas, Procesos Base)
#docker compose exec web python scripts/seed_data.py

# 5. Cargar Feriados desde JSON (NUEVO)
docker compose exec web python seed_holidays.py

# 6. Cargar Histórico desde Excel
docker compose exec web python seed_data_from_excel.py

# 7. Corregir inconsistencias de fechas
docker compose exec web python fix_dates.py

# 8. Reiniciar servicio web para limpiar estados en memoria
docker compose restart web

echo "✅ Sistema reiniciado correctamente."
docker compose logs web -f