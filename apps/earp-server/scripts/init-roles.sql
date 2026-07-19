-- dev/spike environment roles (PRD-2026-020 AC-04 dual-role strategy)
-- superuser "postgres" = migration role (BYPASSRLS by nature)
-- earp_app = application role, subject to FORCE RLS
CREATE ROLE earp_app LOGIN PASSWORD 'earp_app';
GRANT CONNECT ON DATABASE earp TO earp_app;
