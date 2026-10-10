import pytest

from test_pgn import CHECK_FEN, MATE_FEN, from_position


@pytest.mark.parametrize(
    "fen,moves,san",
    [
        (CHECK_FEN, "17. Nc6 Nxf3+", "Nxf3+"),
        (MATE_FEN, "1. Qh7#", "Qh7#"),
    ],
)
def test_add_chapter_preview_accepts_san_suffixes_without_live_write(
    workspace, fen, moves, san
):
    client, remote, _ = workspace
    response = client.post(
        "/api/studies/study001/new-chapter/preview",
        json={
            "name": "Check and mate regression",
            "pgn": from_position(fen, moves),
        },
    )
    assert response.status_code == 200, response.text
    assert san in response.json()["pgn"]
    assert not any(request.method == "POST" for request in remote.requests)


def test_add_chapter_preview_reports_illegal_move_and_number(workspace):
    client, _, _ = workspace
    response = client.post(
        "/api/studies/study001/new-chapter/preview",
        json={
            "name": "Invalid move",
            "pgn": from_position(CHECK_FEN, "17. Nc6 Nxf4+"),
        },
    )
    assert response.status_code == 409
    assert "Illegal chess move at 17... Nxf4+" in response.json()["detail"]


@pytest.mark.parametrize(
    "fen,moves,san",
    [
        (CHECK_FEN, "17. Nc6 Nxf3+", "Nxf3+"),
        (MATE_FEN, "1. Qh7#", "Qh7#"),
    ],
)
def test_mocked_import_storage_and_export_preserve_suffix(workspace, fen, moves, san):
    client, _, app = workspace
    app.state.client.credentials.save(
        "unit-test-token", ["study:read", "study:write"], 3600
    )
    preview = client.post(
        "/api/studies/study001/new-chapter/preview",
        json={
            "name": "Suffix round-trip",
            "pgn": from_position(fen, moves),
        },
    )
    assert preview.status_code == 200, preview.text
    result = client.post(
        "/api/studies/study001/new-chapter/push",
        json={
            "confirmed": True,
            "token": preview.json()["token"],
        },
    )
    assert result.status_code == 200, result.text
    stored = client.get("/api/chapters/study001/chapter9").json()
    assert stored["nodes"][-1]["san"] == san
    exported = client.get("/api/chapters/study001/chapter9/export")
    assert exported.status_code == 200 and san in exported.text
