#!/bin/bash
set -e

echo "🚀 Iniciando el primer despliegue de Talento Up..."

# 1. Comprobar y crear archivos de entorno si no existen
if [ ! -f .env ]; then
  echo "⚠️ Archivo .env no encontrado. Creándolo desde .env.example..."
  cp .env.example .env
fi

if [ ! -f .env.db ]; then
  echo "⚠️ Archivo .env.db no encontrado. Creándolo desde .env.db.example..."
  cp .env.db.example .env.db
fi

# 2. Levantar los contenedores de Docker
echo "📦 Compilando y levantando contenedores en segundo plano..."
docker compose up -d --build

# 3. Esperar a que la base de datos esté lista y saludable
echo "⏳ Esperando a que el motor de base de datos Postgres esté en línea..."
until docker compose exec db pg_isready -U admin > /dev/null 2>&1; do
  echo "⌛ Esperando a la base de datos..."
  sleep 2
done

echo "✅ Base de datos lista."
echo "⏳ Dando un momento a la aplicación para inicializar tablas y el usuario administrador..."
sleep 5

# 4. Importar datos iniciales de la nómina
echo "📊 Cargando datos históricos desde Excel a PostgreSQL..."
docker compose exec web python scripts/migrate_excel_to_pg.py

# 5. Normalizar la estructura de datos importada
echo "🏗️ Normalizando sedes, áreas, cargos y migrando empleados..."
docker compose exec web python scripts/full_migration.py

# 6. Sembrar feriados desde JSON
echo "📅 Sembrando catálogo de feriados nacionales en el sistema..."
docker compose exec web python seed_holidays.py

# 7. Reiniciar el servicio web para limpiar caché
echo "🔄 Reiniciando aplicación web para refrescar configuraciones..."
docker compose restart web

echo "=========================================================================="
echo "🎉 ¡DESPLIEGUE INICIAL COMPLETADO CON ÉXITO!"
echo "=========================================================================="
echo "Puedes acceder al sistema a través de las siguientes URLs:"
echo ""
echo "🔹 Dominio principal (Landing page): http://localhost:8006/"
echo "🔹 Panel de Administración Global:   http://localhost:8006/admin"
echo ""
echo "🔑 Credenciales de Staff / SuperAdmin por defecto:"
echo "👉 Usuario: superadmin@example.com"
echo "👉 Clave:   superpassword"
echo ""
echo "💡 Nota sobre Tenants:"
echo "Para operar con subdominios (por ejemplo, cliente1.localhost),"
echo "asegúrate de registrar el tenant en el Panel de Administración Global."
echo "Luego podrás ingresar a: http://cliente1.localhost:8006/"
echo "=========================================================================="
