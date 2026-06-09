#!/bin/bash
set -e

echo "🔄 Iniciando reseteo completo del sistema..."

# 1. Detener contenedores y eliminar volúmenes (limpieza total de base de datos)
echo "🧹 Deteniendo contenedores y eliminando volúmenes para una limpieza completa..."
docker compose down -v

# 2. Reconstruir e iniciar contenedores
echo "⚙️ Reconstruyendo imágenes e iniciando contenedores..."
docker compose build --no-cache
docker compose up -d

# 3. Esperar a que la base de datos esté lista
echo "⏳ Esperando a que la base de datos esté lista y saludable..."
# Usamos docker compose exec para esperar de manera segura o un bucle de ping
until docker compose exec db pg_isready -U admin > /dev/null 2>&1; do
  echo "⌛ Esperando a la base de datos..."
  sleep 2
done

echo "✅ Base de datos lista. La aplicación iniciará y creará las tablas automáticamente..."
sleep 5

# 4. Migración e importación de la nómina de Excel
echo "📊 Importando datos desde el archivo Excel..."
docker compose exec web python scripts/migrate_excel_to_pg.py

# 5. Normalización y migración de empleados/cargos/sedes
echo "🏗️ Normalizando estructuras de la organización y migrando empleados..."
docker compose exec web python scripts/full_migration.py

# 6. Cargar Feriados Nacionales
echo "📅 Cargando feriados y días no laborales desde JSON..."
docker compose exec web python seed_holidays.py

# 7. Reiniciar la app web para limpiar estados en memoria
echo "🔄 Reiniciando el contenedor web para aplicar cambios..."
docker compose restart web

echo "✨ El sistema ha sido reseteado y cargado con éxito. Listo para operar."
docker compose logs web -f
