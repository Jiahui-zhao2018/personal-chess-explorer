"""Real local HTTP/UI integration with only outbound Lichess traffic mocked."""

import tempfile

import httpx
import uvicorn

from app.db import Chapter, Study
from app.main import create_app
from app.pgn import serialize, one
from app.service import reindex, snapshot
from conftest import Remote, pgn

temporary = tempfile.TemporaryDirectory(prefix="pce-browser-")
remote = Remote()
app = create_app(temporary.name, httpx.MockTransport(remote.handle))
with app.state.sessions.begin() as db:
    db.add(
        Study(
            id="study001",
            label="White repertoire",
            category="White repertoire",
            title="My repertoire",
            enabled=True,
        )
    )
    db.flush()
    source = serialize(one(pgn()))
    c = Chapter(
        id="study001/chapter1",
        study_id="study001",
        remote_id="chapter1",
        name="Opening",
        base=source,
        local=source,
        remote=source,
        status="synced",
    )
    db.add(c)
    db.flush()
    snapshot(db, c, source)
    reindex(db, c)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, access_log=False)
