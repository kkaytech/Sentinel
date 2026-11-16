-- Sentinel database roles (ARD §7.3.1). Run once by the bootstrap superuser.
-- psql variables: owner_password, app_password, reader_password.
-- Objects, grants and triggers are created by Alembic migrations as sentinel_owner.

CREATE ROLE sentinel_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'owner_password';

CREATE ROLE sentinel_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    NOINHERIT CONNECTION LIMIT 20 PASSWORD :'app_password';

CREATE ROLE sentinel_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    NOINHERIT CONNECTION LIMIT 5 PASSWORD :'reader_password';
