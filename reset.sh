#!/bin/bash
set -e

echo "🔄 Iniciando reseteo completo del sistema (Multi-tenant)..."

# 1. Detener contenedores y eliminar volúmenes (limpieza total de base de datos)
echo "🧹 Deteniendo contenedores y eliminando volúmenes de base de datos..."
docker compose down -v

# 2. Reconstruir e iniciar contenedores
echo "⚙️ Reconstruyendo imágenes e iniciando servicios..."
docker compose build --no-cache
docker compose up -d

# 3. Esperar a que la base de datos esté lista
echo "⏳ Esperando a que la base de datos esté lista y saludable..."
until docker compose exec db pg_isready -U admin -d postgres > /dev/null 2>&1; do
  echo "⌛ Esperando a la base de datos..."
  sleep 2
done

echo "✅ Base de datos lista."
echo "🚀 La aplicación se ha iniciado de forma limpia. Las tablas de la administración global (esquema public) y el superadmin se crearán automáticamente al arrancar."

echo "✨ El sistema ha sido reseteado con éxito. Listo para operar."
docker compose logs web -f
