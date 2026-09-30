"""POST /admin/spotify-playlists/regenerate (MysteryMixClub-lz7c).

Spotify generation was only ever queued when voting opened, and a failed job was
never retried, so a mix whose playlist came out wrong had no way back. This admin
endpoint enqueues the same job through the same queue. It must stay narrow: platform
admins only, only mixes in ``open_voting``, one job per mix at a time, and a dry run
that changes nothing.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models.mix import Mix
from app.models.playlist_job import PlaylistJob
from tests.test_spotify_routes import (
    _SHARED_ACCOUNT_ID,
    _seed_mix,
    _seed_shared_account,
    _seed_user,
)

URL = "/api/v1/admin/spotify-playlists/regenerate"
ADMIN_EMAIL = "admin@example.com"


def _client(session_factory, *, account_id: uuid.UUID | None = _SHARED_ACCOUNT_ID) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development",
        seed_admin_emails=ADMIN_EMAIL,
        spotify_playlist_account_user_id=str(account_id) if account_id else "",
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def api(session_factory) -> AsyncGenerator[AsyncClient, None]:
    async with _client(session_factory) as ac:
        yield ac


def _auth(user_id) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _admin(db_session):
    return await _seed_user(db_session, ADMIN_EMAIL)


async def _mix_in(db_session, email: str, state: str) -> Mix:
    """A mix in its own club, in ``state``."""
    organizer = await _seed_user(db_session, email)
    return await _seed_mix(db_session, organizer, state=state)


async def _jobs(db_session, mix_id) -> list[PlaylistJob]:
    db_session.expire_all()
    return list(
        await db_session.scalars(
            select(PlaylistJob).where(
                PlaylistJob.mix_id == mix_id, PlaylistJob.provider == "spotify"
            )
        )
    )


async def _add_job(db_session, mix_id, status: str) -> None:
    db_session.add(PlaylistJob(mix_id=mix_id, provider="spotify", status=status))
    await db_session.commit()


# --------------------------------------------------------------------------- #
# Authorization + configuration gates
# --------------------------------------------------------------------------- #


async def test_unauthenticated_is_401(api):
    assert (await api.post(URL)).status_code == 401


async def test_a_non_admin_is_403_and_queues_nothing(api, db_session):
    await _seed_shared_account(db_session)
    member = await _seed_user(db_session, "member@example.com")
    mix_ = await _mix_in(db_session, "o@example.com", "open_voting")
    mix_id = mix_.id  # capture before expire_all(): an expired attr raises MissingGreenlet

    resp = await api.post(URL, headers=_auth(member.id))

    assert resp.status_code == 403
    assert await _jobs(db_session, mix_id) == []


async def test_unconfigured_environment_is_409_not_a_silently_no_op_job(
    session_factory, db_session
):
    admin = await _admin(db_session)
    await _mix_in(db_session, "o@example.com", "open_voting")
    async with _client(session_factory, account_id=None) as ac:
        resp = await ac.post(URL, headers=_auth(admin.id))
    assert resp.status_code == 409
    assert "not configured" in resp.json()["detail"]


async def test_a_shared_account_that_never_connected_is_409(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session, connected=False)
    await _mix_in(db_session, "o@example.com", "open_voting")

    resp = await api.post(URL, headers=_auth(admin.id))

    assert resp.status_code == 409
    assert "not been connected" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Default target: every mix in voting
# --------------------------------------------------------------------------- #


async def test_no_body_queues_every_mix_in_voting_and_only_those(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting_a = await _mix_in(db_session, "a@example.com", "open_voting")
    voting_b = await _mix_in(db_session, "b@example.com", "open_voting")
    closed = await _mix_in(db_session, "c@example.com", "closed")
    submitting = await _mix_in(db_session, "d@example.com", "open_submission")
    ids = {"a": voting_a.id, "b": voting_b.id, "closed": closed.id, "sub": submitting.id}

    resp = await api.post(URL, headers=_auth(admin.id))

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["dry_run"] is False
    assert (body["queued"], body["already_active"], body["skipped"]) == (2, 0, 0)
    assert {r["mix_id"] for r in body["results"]} == {str(ids["a"]), str(ids["b"])}
    assert all(r["status"] == "queued" for r in body["results"])
    for key in ("a", "b"):
        (job,) = await _jobs(db_session, ids[key])
        assert job.status == "queued"
    assert await _jobs(db_session, ids["closed"]) == []
    assert await _jobs(db_session, ids["sub"]) == []


async def test_results_use_the_wire_vocabulary(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    mix_ = await _mix_in(db_session, "a@example.com", "open_voting")
    club_id = mix_.club_id

    (row,) = (await api.post(URL, headers=_auth(admin.id))).json()["results"]

    assert set(row) == {"mix_id", "club_id", "mix_number", "status", "reason"}
    assert row["club_id"] == str(club_id)
    assert row["mix_number"] == 1


async def test_an_empty_json_body_behaves_like_no_body(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    await _mix_in(db_session, "a@example.com", "open_voting")

    resp = await api.post(URL, json={}, headers=_auth(admin.id))

    assert resp.status_code == 202
    assert resp.json()["queued"] == 1


async def test_nothing_in_voting_is_a_200_with_nothing_queued(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    await _mix_in(db_session, "a@example.com", "closed")

    resp = await api.post(URL, headers=_auth(admin.id))

    assert resp.status_code == 200  # nothing was accepted for processing
    assert resp.json() == {
        "dry_run": False,
        "queued": 0,
        "already_active": 0,
        "skipped": 0,
        "results": [],
    }


# --------------------------------------------------------------------------- #
# Explicit targets
# --------------------------------------------------------------------------- #


async def test_explicit_ids_queue_the_voting_mix_and_skip_the_rest_with_a_reason(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting = await _mix_in(db_session, "a@example.com", "open_voting")
    closed = await _mix_in(db_session, "b@example.com", "closed")
    pending = await _mix_in(db_session, "c@example.com", "pending")
    voting_id, closed_id, pending_id = voting.id, closed.id, pending.id

    resp = await api.post(
        URL,
        json={"mix_ids": [str(voting_id), str(closed_id), str(pending_id)]},
        headers=_auth(admin.id),
    )

    assert resp.status_code == 202
    by_id = {r["mix_id"]: r for r in resp.json()["results"]}
    assert by_id[str(voting_id)]["status"] == "queued"
    assert by_id[str(closed_id)] == {
        **by_id[str(closed_id)],
        "status": "skipped",
        "reason": "mix is closed, not open_voting",
    }
    assert by_id[str(pending_id)]["reason"] == "mix is pending, not open_voting"
    assert (resp.json()["queued"], resp.json()["skipped"]) == (1, 2)
    assert len(await _jobs(db_session, voting_id)) == 1
    assert await _jobs(db_session, closed_id) == []
    assert await _jobs(db_session, pending_id) == []


async def test_one_unknown_id_fails_the_whole_call_so_a_typo_cannot_skip_a_mix(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting = await _mix_in(db_session, "a@example.com", "open_voting")
    voting_id = voting.id
    ghost = uuid.uuid4()

    resp = await api.post(
        URL, json={"mix_ids": [str(voting_id), str(ghost)]}, headers=_auth(admin.id)
    )

    assert resp.status_code == 404
    assert str(ghost) in resp.json()["detail"]
    assert await _jobs(db_session, voting_id) == []  # nothing queued, not even the valid one


async def test_duplicate_ids_queue_one_job(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting = await _mix_in(db_session, "a@example.com", "open_voting")
    voting_id = voting.id

    resp = await api.post(URL, json={"mix_ids": [str(voting_id)] * 3}, headers=_auth(admin.id))

    assert len(resp.json()["results"]) == 1
    assert len(await _jobs(db_session, voting_id)) == 1


async def test_an_empty_id_list_is_rejected_not_read_as_everything(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting = await _mix_in(db_session, "a@example.com", "open_voting")
    voting_id = voting.id

    resp = await api.post(URL, json={"mix_ids": []}, headers=_auth(admin.id))

    assert resp.status_code == 422
    assert await _jobs(db_session, voting_id) == []


async def test_more_than_the_cap_is_rejected(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    ids = [str(uuid.uuid4()) for _ in range(101)]

    resp = await api.post(URL, json={"mix_ids": ids}, headers=_auth(admin.id))

    assert resp.status_code == 422
    assert "at most 100" in resp.json()["detail"]


async def test_a_malformed_id_is_a_422(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    resp = await api.post(URL, json={"mix_ids": ["not-a-uuid"]}, headers=_auth(admin.id))
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# One job per mix at a time
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("active_status", ["queued", "running"])
async def test_a_mix_with_an_active_job_is_reported_already_active_and_not_doubled(
    api, db_session, active_status
):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting = await _mix_in(db_session, "a@example.com", "open_voting")
    voting_id = voting.id
    await _add_job(db_session, voting_id, active_status)

    resp = await api.post(URL, headers=_auth(admin.id))

    (row,) = resp.json()["results"]
    assert row["status"] == "already_active"
    assert resp.json()["already_active"] == 1
    assert len(await _jobs(db_session, voting_id)) == 1
    assert resp.status_code == 200  # nothing new was accepted


@pytest.mark.parametrize("terminal_status", ["complete", "failed"])
async def test_a_finished_job_does_not_block_a_new_one(api, db_session, terminal_status):
    # The whole point: a FAILED job is exactly what needs re-running.
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting = await _mix_in(db_session, "a@example.com", "open_voting")
    voting_id = voting.id
    await _add_job(db_session, voting_id, terminal_status)

    resp = await api.post(URL, headers=_auth(admin.id))

    assert resp.status_code == 202
    statuses = sorted(j.status for j in await _jobs(db_session, voting_id))
    assert statuses == sorted([terminal_status, "queued"])


async def test_calling_twice_queues_one_job_and_reports_the_second_as_already_active(
    api, db_session
):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    voting = await _mix_in(db_session, "a@example.com", "open_voting")
    voting_id = voting.id

    first = await api.post(URL, headers=_auth(admin.id))
    second = await api.post(URL, headers=_auth(admin.id))

    assert first.json()["results"][0]["status"] == "queued"
    assert second.json()["results"][0]["status"] == "already_active"
    assert len(await _jobs(db_session, voting_id)) == 1


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


async def test_dry_run_reports_what_would_happen_and_changes_nothing(api, db_session):
    admin = await _admin(db_session)
    await _seed_shared_account(db_session)
    fresh = await _mix_in(db_session, "a@example.com", "open_voting")
    busy = await _mix_in(db_session, "b@example.com", "open_voting")
    fresh_id, busy_id = fresh.id, busy.id
    await _add_job(db_session, busy_id, "running")

    resp = await api.post(URL, json={"dry_run": True}, headers=_auth(admin.id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    by_id = {r["mix_id"]: r["status"] for r in body["results"]}
    assert by_id == {str(fresh_id): "would_queue", str(busy_id): "already_active"}
    assert await _jobs(db_session, fresh_id) == []
    assert len(await _jobs(db_session, busy_id)) == 1  # untouched


async def test_dry_run_still_enforces_the_configuration_gate(session_factory, db_session):
    admin = await _admin(db_session)
    async with _client(session_factory, account_id=None) as ac:
        resp = await ac.post(URL, json={"dry_run": True}, headers=_auth(admin.id))
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# The recovery story, end to end: fail -> regenerate -> succeed
# --------------------------------------------------------------------------- #


async def test_a_failed_run_can_be_regenerated_and_the_worker_then_completes_it(
    real_session_factory, real_db_session, monkeypatch
):
    """The whole reason this endpoint exists. A run where Spotify refuses the lookups
    fails (MysteryMixClub-gz6c) without touching the playlist; nothing re-enqueues it
    on its own; the admin regenerates; the worker then builds the full playlist."""
    from app.jobs.playlist_worker import _drain_queue
    from app.services.spotify_client import IsrcLookup
    from tests.test_playlist_worker import _NoopYouTube
    from tests.test_spotify_routes import FakeSpotifyClient, _add_submission, _seed_member

    monkeypatch.setattr("app.jobs.playlist_worker.async_session_factory", real_session_factory)
    settings = Settings(spotify_playlist_account_user_id=str(_SHARED_ACCOUNT_ID))

    admin = await _admin(real_db_session)
    admin_id = admin.id  # _jobs() expires the session; an expired attr raises MissingGreenlet
    organizer = await _seed_user(real_db_session, "o@example.com")
    mix_ = await _seed_mix(real_db_session, organizer, state="open_voting")
    mix_id = mix_.id
    await _seed_shared_account(real_db_session)
    member = await _seed_member(real_db_session, mix_, "m@example.com")
    await _add_submission(real_db_session, mix_id, organizer.id, isrc="I-0", title="a")
    await _add_submission(real_db_session, mix_id, member.id, isrc="I-1", title="b")

    # Run 1: voting opened, Spotify is refusing every lookup.
    refusing = FakeSpotifyClient(
        lookup_overrides={
            "I-0": IsrcLookup("error", status=403, reason="http"),
            "I-1": IsrcLookup("error", status=403, reason="http"),
        }
    )
    await _add_job(real_db_session, mix_id, "queued")
    assert await _drain_queue(settings, refusing, _NoopYouTube()) == 1
    (first,) = await _jobs(real_db_session, mix_id)
    assert first.status == "failed"
    assert "2 of 2" in (first.error or "")
    assert refusing.created is None  # a truncated playlist was never published

    # Nothing re-enqueues it: the queue stays empty until someone acts.
    assert await _drain_queue(settings, refusing, _NoopYouTube()) == 0

    # The admin regenerates; a failed job does not block a new one.
    async with _client(real_session_factory) as api:
        resp = await api.post(URL, headers=_auth(admin_id))
    assert resp.status_code == 202
    assert resp.json()["results"][0]["status"] == "queued"

    # Run 2: Spotify is healthy again.
    healthy = FakeSpotifyClient(isrc_map={"I-0": "spotify:track:0", "I-1": "spotify:track:1"})
    assert await _drain_queue(settings, healthy, _NoopYouTube()) == 1

    jobs = await _jobs(real_db_session, mix_id)
    assert sorted(j.status for j in jobs) == ["complete", "failed"]
    assert healthy.created is not None
    assert sorted(healthy.added) == ["spotify:track:0", "spotify:track:1"]
