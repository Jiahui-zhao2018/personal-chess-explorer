import chess

from app.db import Occurrence
from conftest import edit_request, pgn


def test_unified_studies_chapters_and_transpositions(workspace):
    client, remote, _ = workspace
    remote.chapters[("study001", "chapter2")] = pgn(
        "1. Nf3 Nf6 2. g3 g6 3. Bg2 *", cid="chapter2"
    )
    remote.chapters[("study002", "chapter3")] = pgn(
        "1. g3 g6 2. Nf3 Nf6 3. d3 *", sid="study002", cid="chapter3"
    )
    assert (
        client.post(
            "/api/studies",
            json={
                "url": "https://lichess.org/study/study002",
                "category": "White",
                "side": "white",
            },
        ).status_code
        == 200
    )
    result = client.post("/api/refresh", json={}).json()
    assert all(r["ok"] for r in result)
    board = chess.Board()
    for move in ["Nf3", "Nf6", "g3", "g6"]:
        board.push_san(move)
    result = client.get("/api/explorer", params={"fen": board.fen()}).json()
    assert {m["san"] for m in result["moves"]} == {"Bg2", "d3"}
    assert {r["chapter_id"] for r in result["occurrences"]} == {
        "study001/chapter2",
        "study002/chapter3",
    }
    assert (
        len(
            client.get(
                "/api/explorer", params={"fen": board.fen(), "category": "White"}
            ).json()["occurrences"]
        )
        == 1
    )
    assert (
        client.patch("/api/studies/study002", json={"enabled": False}).status_code
        == 200
    )
    assert (
        len(
            client.get("/api/explorer", params={"fen": board.fen()}).json()[
                "occurrences"
            ]
        )
        == 1
    )


def test_counts_are_unique_studies_and_chapters(workspace):
    client, remote, _ = workspace
    remote.chapters[("study001", "chapter2")] = pgn(cid="chapter2")
    remote.chapters[("study002", "chapter3")] = pgn(sid="study002", cid="chapter3")
    client.post("/api/studies", json={"url": "study002"})
    client.post("/api/refresh", json={})
    move = client.get("/api/explorer").json()["moves"][0]
    assert (move["studies"], move["chapters"], move["occurrences"]) == (2, 3, 3)
    assert len({r["url"] for r in move["references"]}) == 3


def test_editing_is_one_chapter_and_undo_redo(workspace):
    client, remote, _ = workspace
    remote.chapters[("study001", "chapter2")] = pgn(cid="chapter2")
    client.post("/api/refresh", json={})
    initial = client.get("/api/chapters/study001/chapter1").json()
    assert edit_request(client, "add", "e2e4", uci="e7e6").json()["status"] == "pending"
    assert "e7e6" not in client.get("/api/chapters/study001/chapter2").json()["pgn"]
    undone = edit_request(client, "undo").json()
    assert undone["hash"] == initial["hash"] and undone["can_redo"]
    redone = edit_request(client, "redo").json()
    assert redone["hash"] != initial["hash"] and redone["can_undo"]
    stale = client.post(
        "/api/chapters/study001/chapter1/edit",
        json={"action": "delete", "path": "e2e4", "expected_hash": initial["hash"]},
    )
    assert stale.status_code == 409


def test_search_and_local_remove(workspace):
    client, remote, app = workspace
    assert (
        client.get("/api/search", params={"q": "Sicilian"}).json()[0]["path"]
        == "e2e4/c7c5"
    )
    assert (
        client.get("/api/search", params={"q": chess.STARTING_FEN}).json()[0]["path"]
        == ""
    )
    assert client.request("DELETE", "/api/studies/study001", json={}).status_code == 409
    assert (
        client.request(
            "DELETE", "/api/studies/study001", json={"confirmed": True}
        ).status_code
        == 200
    )
    assert client.get("/api/chapters").json() == []
    assert remote.chapters
    with app.state.sessions() as db:
        assert db.query(Occurrence).count() == 0


def test_custom_start_is_indexed(workspace):
    client, remote, _ = workspace
    fen = "8/8/8/8/8/4k3/8/4K3 w - - 0 1"
    remote.chapters[("study001", "chapter2")] = pgn(
        "1. Kf1 *", cid="chapter2", extra=f'[SetUp "1"]\n[FEN "{fen}"]'
    )
    client.post("/api/refresh", json={})
    result = client.get("/api/explorer", params={"fen": fen}).json()
    assert result["moves"][0]["san"] == "Kf1"
