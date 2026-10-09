import os
from urllib.parse import parse_qs, urlparse


from conftest import pgn


def test_oauth_pkce_scopes_and_secure_backend_only_storage(workspace):
    client, _, app = workspace
    start = client.get("/api/auth/connect", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)
    assert params["scope"] == ["study:read"]
    assert params["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in params
    invalid = client.get(
        "/api/auth/callback", params={"state": "invalid", "code": "code"}
    )
    assert invalid.status_code == 400
    callback = client.get(
        "/api/auth/callback",
        params={"state": params["state"][0], "code": "test-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 307
    status = client.get("/api/auth/status").json()
    assert status["authenticated"] and not status["write"] and "token" not in status
    path = app.state.client.credentials.path
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert client.post("/api/auth/disconnect", json={}).status_code == 200
    assert not path.exists()


def test_expired_credentials_and_csrf(workspace):
    client, _, app = workspace
    app.state.client.credentials.save("expired", ["study:write"], -1)
    assert not client.get("/api/auth/status").json()["authenticated"]
    assert (
        client.post(
            "/api/refresh", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/refresh", content="{}", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    )


def test_training_hides_answers_accepts_alternatives_and_schedules_locally(workspace):
    client, remote, _ = workspace
    remote.chapters[("study001", "chapter1")] = pgn(
        "1. e4 {King pawn} (1. d4 {Queen pawn}) e5 *"
    )
    client.post("/api/refresh", json={})
    challenge = client.get("/api/training/next").json()
    assert (
        not challenge["done"]
        and "moves" not in challenge
        and "comment" not in challenge
    )
    answer = client.post(
        "/api/training/answer", json={"token": challenge["token"], "uci": "d2d4"}
    )
    assert answer.status_code == 200 and answer.json()["correct"]
    assert len(answer.json()["moves"]) == 2
    assert (
        client.post(
            "/api/training/answer", json={"token": challenge["token"], "uci": "e2e4"}
        ).status_code
        == 409
    )
    progress = client.get("/api/training/progress").json()
    assert (progress["attempts"], progress["correct"]) == (1, 1)
    assert not any(r.method == "POST" for r in remote.requests)


def test_training_wrong_answer_and_side_filter(workspace):
    client, _, _ = workspace
    challenge = client.get("/api/training/next", params={"side": "black"}).json()
    assert challenge["fen"].split()[1] == "b"
    answer = client.post(
        "/api/training/answer", json={"token": challenge["token"], "uci": "a7a6"}
    ).json()
    assert not answer["correct"]
    assert {m["san"] for m in answer["moves"]} == {"e5", "c5"}
