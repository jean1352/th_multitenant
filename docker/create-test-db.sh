#!/bin/sh
set -eu

export PGPASSWORD="$POSTGRES_PASSWORD"

database_exists="$(psql --username="$POSTGRES_USER" --tuples-only --no-align \
  --command="SELECT 1 FROM pg_database WHERE datname = 'talento_up_test'")"

if [ "$database_exists" != "1" ]; then
  createdb --username="$POSTGRES_USER" talento_up_test
fi

echo "Base E2E disponible: talento_up_test."
