"""MYS-37 — DigitalOcean deploy specs must run DB migrations on deploy.

Today neither `.do/app.staging.yaml` nor `.do/app.prod.yaml` runs
`alembic upgrade head`, so deployed environments never receive the schema.
The fix adds a DigitalOcean PRE_DEPLOY job to each spec that runs the
migrations against the same managed DB the `api` service uses.

These tests assert that contract. They are TDD-first and are expected to
FAIL until the PRE_DEPLOY migrate job is added to each spec.
"""

from pathlib import Path

import pytest
import yaml

# `.do` lives two levels up from backend/tests/.
DO_DIR = Path(__file__).resolve().parents[2] / ".do"

SPEC_FILES = ["app.staging.yaml", "app.prod.yaml"]


def _load_spec(filename: str) -> dict:
    spec_path = DO_DIR / filename
    # Fail loudly on a bad path rather than silently passing/erroring elsewhere.
    assert spec_path.exists(), f"DO spec not found at resolved path: {spec_path}"
    with spec_path.open() as fh:
        spec = yaml.safe_load(fh)
    assert isinstance(spec, dict), f"{filename} did not parse to a mapping"
    return spec


def _find_api_service(spec: dict, filename: str) -> dict:
    services = spec.get("services")
    assert isinstance(services, list), f"{filename}: expected a top-level 'services' list"
    api = next((s for s in services if s.get("name") == "api"), None)
    assert api is not None, f"{filename}: no service named 'api' (wrong file?)"
    return api


def _env_by_key(envs, key):
    if not isinstance(envs, list):
        return None
    return next((e for e in envs if isinstance(e, dict) and e.get("key") == key), None)


@pytest.mark.parametrize("filename", SPEC_FILES)
def test_spec_has_expected_shape(filename):
    """Sanity check: the file is the DO spec we think it is."""
    spec = _load_spec(filename)
    api = _find_api_service(spec, filename)
    # api service uses backend as source and binds DATABASE_URL to the managed db.
    assert api.get("source_dir") == "backend", (
        f"{filename}: api service source_dir is not 'backend'"
    )
    api_db_env = _env_by_key(api.get("envs"), "DATABASE_URL")
    assert api_db_env is not None, f"{filename}: api service is missing DATABASE_URL env"
    assert api_db_env.get("value") == "${db.DATABASE_URL}", (
        f"{filename}: api DATABASE_URL not bound to the managed db component"
    )


@pytest.mark.parametrize("filename", SPEC_FILES)
def test_spec_has_pre_deploy_migration_job(filename):
    """A PRE_DEPLOY job must run `alembic upgrade head` against the managed DB."""
    spec = _load_spec(filename)
    # Sanity: confirm it is the right file before asserting on jobs.
    _find_api_service(spec, filename)

    jobs = spec.get("jobs")
    assert isinstance(jobs, list) and jobs, (
        f"{filename}: expected a non-empty top-level 'jobs' list defining a "
        f"PRE_DEPLOY migration job; found {jobs!r}"
    )

    pre_deploy_jobs = [j for j in jobs if isinstance(j, dict) and j.get("kind") == "PRE_DEPLOY"]
    assert pre_deploy_jobs, f"{filename}: no job with kind == 'PRE_DEPLOY' found in jobs list"

    # The migration job is the PRE_DEPLOY job that runs alembic.
    migrate_jobs = [
        j for j in pre_deploy_jobs if "alembic upgrade head" in (j.get("run_command") or "")
    ]
    assert migrate_jobs, (
        f"{filename}: no PRE_DEPLOY job whose run_command contains 'alembic upgrade head'"
    )

    job = migrate_jobs[0]

    # Wired to the same managed DB as the api service.
    db_env = _env_by_key(job.get("envs"), "DATABASE_URL")
    assert db_env is not None, f"{filename}: PRE_DEPLOY migrate job is missing a DATABASE_URL env"
    assert db_env.get("type") == "SECRET", (
        f"{filename}: PRE_DEPLOY migrate job DATABASE_URL env is not type SECRET"
    )
    assert db_env.get("value") == "${db.DATABASE_URL}", (
        f"{filename}: PRE_DEPLOY migrate job DATABASE_URL not bound to "
        f"'${{db.DATABASE_URL}}' (got {db_env.get('value')!r})"
    )

    # Uses the backend as source so alembic + the app package are present.
    assert job.get("source_dir") == "backend", (
        f"{filename}: PRE_DEPLOY migrate job source_dir is not 'backend' "
        f"(got {job.get('source_dir')!r})"
    )
