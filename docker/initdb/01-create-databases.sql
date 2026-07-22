-- Runs automatically the first time the Postgres container initializes an empty
-- data directory (Postgres executes every *.sql / *.sh in /docker-entrypoint-initdb.d).
--
-- The application database (mysterymixclub) is created by POSTGRES_DB. This adds
-- the throwaway database the backend test suite expects: tests/conftest.py builds
-- the schema via create_all against mysterymixclub_test, so it must already exist.
--
-- Owned by POSTGRES_USER (mmc) since the init scripts run as that role.
CREATE DATABASE mysterymixclub_test;
