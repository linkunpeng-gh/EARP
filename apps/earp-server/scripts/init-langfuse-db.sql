-- Init script: create langfuse database for docker-compose
-- Postgres runs init scripts alphabetically, so 02-* runs after 01-roles.sql

SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
