#!/bin/bash
set -e

echo "🚀 Iniciando el primer despliegue de Talento Up (Multi-tenant)..."

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
until docker compose exec db pg_isready -U admin -d postgres > /dev/null 2>&1; do
  echo "⌛ Esperando a la base de datos..."
  sleep 2
done

echo "✅ Base de datos lista."
echo "🚀 La aplicación web inicializará automáticamente el esquema público, las tablas globales y el usuario administrador en su primer arranque."

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
echo "Al ser una plataforma estrictamente Multi-tenant, todo el aislamiento de"
echo "los datos de la nómina, sedes, áreas, cargos, empleados y feriados se"
echo "realizará dentro del esquema de cada inquilino que crees."
echo ""
echo "Para operar, primero ingresa a la Administración Global, crea un nuevo"
echo "Tenant (ej. 'cliente1') y podrás acceder a él desde:"
echo "👉 URL: http://cliente1.localhost:8006/"
echo "=========================================================================="
