import re
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.pgn import one, serialize


def pgn(
    moves="1. e4 {Main idea} e5 (1... c5 $1 {Sicilian} 2. Nf3 (2. Nc3)) 2. Nf3 *",
    sid="study001",
    cid="chapter1",
    extra="",
):
    return f'[Event "Repertoire"]\n[StudyName "My repertoire"]\n[ChapterName "Opening"]\n[ChapterURL "https://lichess.org/study/{sid}/{cid}"]\n[Result "*"]\n{extra}\n{moves}\n'


class Remote:
    def __init__(self):
        self.chapters = {("study001", "chapter1"): pgn()}
        self.requests = []
        self.fail = None
        self.verify_fail = False
        self.after_write = False
        self.callback = None

    def handle(self, request):
        self.requests.append(request)
        if self.callback:
            self.callback(request)
        if self.fail:
            mode, method = self.fail
            if request.method == method:
                if mode == "timeout":
                    raise httpx.ReadTimeout("mock timeout", request=request)
                return httpx.Response(mode)
        path = request.url.path
        match = re.fullmatch(r"/api/study/(\w+)/(\w+)(?:\.pgn|/(moves|tags))", path)
        if match:
            sid, cid, action = match.groups()
            source = self.chapters.get((sid, cid))
            if source is None:
                return httpx.Response(404)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text=pgn("1. d4 *", sid, cid)
                    if self.verify_fail and self.after_write
                    else source,
                )
            data = parse_qs(request.content.decode(), keep_blank_values=True)["pgn"][0]
            if action == "moves":
                incoming = one(data)
                incoming.headers = one(source).headers.copy()
                self.chapters[(sid, cid)] = serialize(incoming)
            elif action == "tags":
                game = one(source)
                for k, v in re.findall(r'\[(\w+) "([^"\n]*)"\]', data):
                    if v:
                        game.headers[k] = v
                    else:
                        game.headers.pop(k, None)
                self.chapters[(sid, cid)] = serialize(game)
            self.after_write = True
            return httpx.Response(204)
        match = re.fullmatch(r"/api/study/(\w+)\.pgn", path)
        if match:
            games = [g for (sid, _), g in self.chapters.items() if sid == match[1]]
            return (
                httpx.Response(200, text="\n\n".join(games))
                if games
                else httpx.Response(404)
            )
        if path == "/api/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "secret-for-tests",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        if path.endswith("/import-pgn"):
            sid = path.split("/")[3]
            data = parse_qs(request.content.decode())
            game = one(data["pgn"][0])
            game.headers["ChapterURL"] = f"https://lichess.org/study/{sid}/chapter9"
            game.headers["StudyName"] = "My repertoire"
            game.headers["ChapterName"] = data["name"][0]
            self.chapters[(sid, "chapter9")] = serialize(game)
            return httpx.Response(
                200,
                json={
                    "chapters": [{"id": "chapter9", "name": data["name"][0]}],
                    "error": None,
                },
            )
        return httpx.Response(404)


@pytest.fixture
def workspace(tmp_path):
    remote = Remote()
    app = create_app(
        tmp_path, httpx.MockTransport(remote.handle), write_study_ids={"study001"}
    )
    with TestClient(app) as client:
        assert client.post("/api/studies", json={"url": "study001"}).status_code == 200
        assert client.post("/api/studies/study001/refresh", json={}).status_code == 200
        yield client, remote, app


def edit_request(client, action, path="", **args):
    current = client.get("/api/chapters/study001/chapter1").json()
    return client.post(
        "/api/chapters/study001/chapter1/edit",
        json={"expected_hash": current["hash"], "action": action, "path": path, **args},
    )


def pending(client):
    assert (
        edit_request(
            client, "annotate", "e2e4", comment="Local idea", nags=[1, 14]
        ).status_code
        == 200
    )


def preview(client):
    response = client.post("/api/chapters/study001/chapter1/preview", json={})
    assert response.status_code == 200, response.text
    return response.json()
