import pytest

from app.db import Backup, Chapter, Snapshot
from app.pgn import digest, one
from conftest import edit_request, pending, pgn, preview


def allow(app):
    app.state.client.credentials.save("test-token", ["study:read", "study:write"], 3600)


def push(client, p, **args):
    return client.post(
        "/api/chapters/study001/chapter1/push",
        json={"token": p["token"], "confirmed": True, **args},
    )


def test_no_change_pull_is_idempotent(workspace):
    client, _, app = workspace
    before = client.get("/api/chapters/study001/chapter1").json()
    assert client.post("/api/refresh", json={}).status_code == 200
    after = client.get("/api/chapters/study001/chapter1").json()
    assert before["hash"] == after["hash"] and after["status"] == "synced"
    with app.state.sessions() as db:
        assert db.query(Snapshot).count() == 1


def test_remote_only_pull_updates_local(workspace):
    client, remote, _ = workspace
    remote.chapters[("study001", "chapter1")] = pgn("1. d4 {Remote only} d5 *")
    assert client.post("/api/refresh", json={}).json()[0]["ok"]
    chapter = client.get("/api/chapters/study001/chapter1").json()
    assert chapter["status"] == "synced" and "Remote only" in chapter["pgn"]


def test_local_only_pull_keeps_pending_and_conflict_keeps_all_versions(workspace):
    client, remote, app = workspace
    pending(client)
    client.post("/api/refresh", json={})
    assert client.get("/api/chapters/study001/chapter1").json()["status"] == "pending"
    remote.chapters[("study001", "chapter1")] = pgn("1. e4 {Remote idea} e5 *")
    client.post("/api/refresh", json={})
    c = client.get("/api/chapters/study001/chapter1").json()
    assert c["status"] == "conflict" and "Local idea" in c["pgn"]
    with app.state.sessions() as db:
        c = db.get(Chapter, "study001/chapter1")
        assert "Main idea" in c.base and "Remote idea" in c.remote


def test_successful_push_keeps_siblings_comments_nags_backup_and_verification(
    workspace,
):
    client, remote, app = workspace
    allow(app)
    pending(client)
    baseline = remote.chapters[("study001", "chapter1")]
    p = preview(client)
    assert "Local idea" in p["local_diff"] and p["status"] == "pending"
    result = push(client, p)
    assert result.status_code == 200, result.text
    chapter = client.get("/api/chapters/study001/chapter1").json()
    assert chapter["status"] == "synced" and not chapter["can_undo"]
    assert "Sicilian" in chapter["pgn"] and "$14" in chapter["pgn"]
    backup = client.get("/api/backups/" + str(result.json()["backup_id"]))
    assert digest(backup.text) == digest(baseline)
    assert sum(r.method == "POST" for r in remote.requests) == 1
    assert remote.requests[-1].method == "GET"
    assert push(client, p).status_code == 409  # one-use preview


def test_tags_are_separate_and_deletions_are_explicit(workspace):
    client, remote, app = workspace
    allow(app)
    edit_request(client, "tags", tags={"Opening": "Ruy Lopez", "ECO": "C60"})
    assert push(client, preview(client)).status_code == 200
    posts = [r for r in remote.requests if r.method == "POST"]
    assert [r.url.path for r in posts] == ["/api/study/study001/chapter1/tags"]
    edit_request(client, "tags", tags={"Opening": ""})
    assert push(client, preview(client)).status_code == 200
    assert "Opening" not in one(remote.chapters[("study001", "chapter1")]).headers


def test_conflict_never_implicitly_overwrites_and_explicit_overwrite_works(workspace):
    client, remote, app = workspace
    allow(app)
    pending(client)
    remote.chapters[("study001", "chapter1")] = pgn("1. e4 {Concurrent} e5 *")
    p = preview(client)
    assert p["status"] == "conflict" and "Concurrent" in p["remote_diff"]
    assert push(client, p).status_code == 409
    assert not any(r.method == "POST" for r in remote.requests)
    assert push(client, preview(client), overwrite=True).status_code == 200


def test_remote_changed_after_preview_blocks_even_explicit_overwrite(workspace):
    client, remote, app = workspace
    allow(app)
    pending(client)
    p = preview(client)
    remote.chapters[("study001", "chapter1")] = pgn("1. d4 d5 *")
    result = push(client, p, overwrite=True)
    assert result.status_code == 409 and "after preview" in result.text
    assert not any(r.method == "POST" for r in remote.requests)


def test_local_changed_after_preview_and_confirmation_required(workspace):
    client, remote, app = workspace
    allow(app)
    pending(client)
    p = preview(client)
    response = client.post(
        "/api/chapters/study001/chapter1/push", json={"token": p["token"]}
    )
    assert response.status_code == 409
    edit_request(client, "add", "e2e4", uci="e7e6")
    assert push(client, p).status_code == 409
    assert not any(r.method == "POST" for r in remote.requests)


@pytest.mark.parametrize("fault", [503, 401, 403, "timeout"])
def test_failed_upload_preserves_local_and_base_and_backup(workspace, fault):
    client, remote, app = workspace
    allow(app)
    pending(client)
    p = preview(client)
    remote.fail = (fault, "POST")
    response = push(client, p)
    assert response.status_code in (401, 403, 502)
    c = client.get("/api/chapters/study001/chapter1").json()
    assert c["status"] == "error" and "Local idea" in c["pgn"]
    with app.state.sessions() as db:
        assert "Main idea" in db.get(Chapter, c["id"]).base
        assert db.query(Backup).count() == 1
    assert sum(r.method == "POST" for r in remote.requests) == 1


def test_post_upload_verification_failure_and_recovery(workspace):
    client, remote, app = workspace
    allow(app)
    pending(client)
    p = preview(client)
    remote.verify_fail = True
    response = push(client, p)
    assert response.status_code == 502 and "verification" in response.text
    c = client.get("/api/chapters/study001/chapter1").json()
    assert c["status"] == "error"
    b = client.get("/api/backups").json()[0]
    assert (
        client.post(
            "/api/backups/" + str(b["id"]) + "/restore",
            json={"confirmed": True, "expected_hash": c["hash"]},
        ).status_code
        == 200
    )
    restored = client.get("/api/chapters/study001/chapter1").json()
    assert "Main idea" in restored["pgn"]


def test_read_only_and_remote_resolution(workspace):
    client, remote, app = workspace
    pending(client)
    assert push(client, preview(client)).status_code == 403
    assert not any(r.method == "POST" for r in remote.requests)
    remote.chapters[("study001", "chapter1")] = pgn("1. d4 {Remote wins} *")
    c = client.get("/api/chapters/study001/chapter1").json()
    response = client.post(
        "/api/chapters/study001/chapter1/resolve",
        json={"choice": "remote", "confirmed": True, "expected_hash": c["hash"]},
    )
    assert response.status_code == 200 and response.json()["status"] == "synced"
    assert "Remote wins" in response.json()["pgn"]
    assert "Local idea" in client.get("/api/backups/1").text


def test_manual_resolution_and_remote_removed_chapter(workspace):
    client, remote, _ = workspace
    pending(client)
    c = client.get("/api/chapters/study001/chapter1").json()
    result = client.post(
        "/api/chapters/study001/chapter1/resolve",
        json={
            "choice": "manual",
            "confirmed": True,
            "expected_hash": c["hash"],
            "pgn": pgn("1. c4 *"),
        },
    )
    assert result.status_code == 200 and result.json()["status"] == "pending"
    remote.chapters[("study001", "chapter2")] = pgn("1. d4 *", cid="chapter2")
    del remote.chapters[("study001", "chapter1")]
    client.post("/api/refresh", json={})
    removed = client.get("/api/chapters/study001/chapter1").json()
    assert removed["deleted"] and removed["status"] == "conflict"
    assert (
        client.post("/api/chapters/study001/chapter1/preview", json={}).status_code
        == 409
    )


def test_failed_pull_is_atomic_and_retains_pending(workspace):
    client, remote, _ = workspace
    pending(client)
    remote.chapters[("study001", "chapter2")] = pgn("1. e4 e4 *", cid="chapter2")
    result = client.post("/api/refresh", json={}).json()
    assert not result[0]["ok"]
    assert len(client.get("/api/chapters").json()) == 1
    assert "Local idea" in client.get("/api/chapters/study001/chapter1").json()["pgn"]


def test_new_chapter_validated_confirmed_import_and_verified(workspace):
    client, remote, app = workspace
    allow(app)
    p = client.post(
        "/api/studies/study001/new-chapter/preview",
        json={"name": "Queen pawn", "pgn": "1. d4 d5 *"},
    ).json()
    assert (
        client.post(
            "/api/studies/study001/new-chapter/push",
            json={"token": p["token"], "confirmed": True},
        ).status_code
        == 200
    )
    assert ("study001", "chapter9") in remote.chapters
    assert len(client.get("/api/chapters").json()) == 2
