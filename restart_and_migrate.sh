#!/bin/bash

# Evitar que falle en caso de algún error intermedio que no sea ignorado
set -e

echo "🔄 Reiniciando contenedores de Docker..."
docker compose down
docker compose up -d

echo "⏳ Esperando a que la base de datos esté lista..."
sleep 5

echo "⚡ Aplicando migraciones estructurales..."
# Intenta aplicar migraciones; si ya están aplicadas o hay tablas duplicadas, continúa con '|| true'
docker compose exec -T web python auto_migrate.py apply || true

echo "🔖 Aplicando migración: categorías de salida y etapas de periodo de prueba..."
docker compose exec -T web python migrate_exit_categories_and_probation_stages.py

echo "🎓 Aplicando migración: módulo de capacitaciones v2..."
docker compose exec -T web python migrate_trainings_v2.py

echo "🎉 ¡Sistema reiniciado, cambios aplicados y datos migrados exitosamente!"
