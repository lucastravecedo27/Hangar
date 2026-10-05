#!/bin/sh
# Se ejecuta UNA vez, cuando el volumen de PostgreSQL está vacío (docker-entrypoint-initdb.d).
# La app no puede conectar como superusuario: un superusuario (o un rol con BYPASSRLS) se salta
# las políticas Row-Level Security aunque la tabla tenga FORCE, y el aislamiento entre empresas
# desaparece. Aquí se crea el rol de la app sin privilegios especiales y se le da la base.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -v app_pass="$HANGAR_DB_PASSWORD" <<-'SQL'
	CREATE ROLE hangar LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'app_pass';
	CREATE DATABASE hangar OWNER hangar;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname hangar <<-'SQL'
	ALTER SCHEMA public OWNER TO hangar;
SQL
