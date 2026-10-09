import asyncio

import httpx
from sqlalchemy import text

from app.db import Chapter, Operation
from app.main import create_app
from conftest import edit_request, pending, preview
from test_sync import allow, push


def test_concurrent_push_previews_cannot_duplicate_updates(workspace):
    client, remote, app = workspace
    allow(app)
    pending(client)
    first, second = preview(client), preview(client)

    async def submit():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            return await asyncio.gather(
                *[
                    http.post(
                        "/api/chapters/study001/chapter1/push",
                        json={"token": p["token"], "confirmed": True},
                    )
                    for p in (first, second)
                ]
            )

    results = asyncio.run(submit())
    assert sorted(r.status_code for r in results) == [200, 409]
    assert sum(r.method == "POST" for r in remote.requests) == 1


def test_live_writes_disabled_even_with_oauth_write_scope(workspace):
    client, remote, app = workspace
    allow(app)
    pending(client)
    app.state.client.write_study_ids.clear()
    p = preview(client)
    assert not p["can_write"]
    assert push(client, p).status_code == 403
    assert not any(r.method == "POST" for r in remote.requests)


def test_partial_moves_tags_failure_retains_base_and_backup(workspace):
    client, remote, app = workspace
    allow(app)
    pending(client)
    edit_request(client, "tags", tags={"Opening": "Local opening"})
    p = preview(client)

    def fail_tags(request):
        if request.url.path.endswith("/tags"):
            remote.fail = (503, "POST")

    remote.callback = fail_tags
    assert push(client, p).status_code == 502
    assert "Local idea" in remote.chapters[("study001", "chapter1")]
    assert "Local opening" not in remote.chapters[("study001", "chapter1")]
    with app.state.sessions() as db:
        c = db.get(Chapter, "study001/chapter1")
        assert "Main idea" in c.base and "Local opening" in c.local
    assert len(client.get("/api/backups").json()) == 1


def test_restart_recovers_interrupted_upload_and_schema_is_idempotent(workspace):
    client, _, app = workspace
    pending(client)
    with app.state.sessions.begin() as db:
        c = db.get(Chapter, "study001/chapter1")
        c.status = "uploading"
        db.add(Operation(chapter_id=c.id, state="uploading"))
    restored = create_app(app.state.client.credentials.path.parent)
    with restored.state.sessions() as db:
        c = db.get(Chapter, "study001/chapter1")
        assert c.status == "error" and "Local idea" in c.local and "Main idea" in c.base
        assert db.query(Operation).first().state == "error"
        assert db.execute(text("PRAGMA user_version")).scalar() == 1


def test_rate_limit_read_waits_and_write_is_not_retried(workspace, monkeypatch):
    client, remote, app = workspace
    waits = []

    async def no_sleep(seconds):
        waits.append(seconds)
        remote.fail = None

    monkeypatch.setattr("app.lichess.asyncio.sleep", no_sleep)
    remote.fail = (429, "GET")
    assert client.post("/api/studies/study001/refresh", json={}).status_code == 200
    assert waits == [60]
    allow(app)
    pending(client)
    p = preview(client)
    remote.fail = (429, "POST")
    assert push(client, p).status_code == 429
    assert sum(r.method == "POST" for r in remote.requests) == 1
