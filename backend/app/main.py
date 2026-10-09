import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import chess
import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, or_, func

from .db import (
    Backup,
    Chapter,
    Occurrence,
    Operation,
    Snapshot,
    Study,
    Training,
    chapter_json,
    database,
    now,
    study_json,
)
from .lichess import Credentials, Lichess, LichessError
from .pgn import (
    ID,
    chapter_identity,
    digest,
    edit,
    one,
    position_key,
    serialize,
    semantic,
)
from .service import Sync, accept_remote, reindex, state


class StudyInput(BaseModel):
    url: str
    label: str = Field(default="", max_length=100)
    category: str = Field(default="", max_length=100)
    side: str = "both"
    enabled: bool = True


class EditInput(BaseModel):
    action: str
    path: str = ""
    uci: str = ""
    comment: str | None = None
    nags: list[int] | None = None
    tags: dict[str, str] | None = None
    order: list[str] | None = None
    expected_hash: str


class PushInput(BaseModel):
    token: str
    confirmed: bool = False
    overwrite: bool = False


def create_app(data_dir=None, transport=None, write_study_ids=None):
    folder = Path(
        data_dir
        or os.environ.get("PCE_DATA_DIR", Path(__file__).resolve().parents[2] / "data")
    )
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    sessions = database(folder / "explorer.sqlite")
    credentials = Credentials(folder / "credentials.json")
    allowed_writes = (
        write_study_ids
        if write_study_ids is not None
        else set(filter(None, os.environ.get("PCE_WRITE_STUDY_IDS", "").split(",")))
    )
    client = Lichess(credentials, transport, allowed_writes)
    sync = Sync(sessions, client)
    app = FastAPI(title="Personal Chess Explorer", version="0.1.0")
    app.state.sessions, app.state.client, app.state.sync = sessions, client, sync
    # An interrupted upload has an unknown remote outcome, never an assumed success.
    with sessions.begin() as db:
        for op in db.scalars(select(Operation).where(Operation.state == "uploading")):
            op.state = "error"
            op.detail = (
                "Upload interrupted. Refresh remote and inspect backup before retrying."
            )
        for c in db.scalars(select(Chapter).where(Chapter.status == "uploading")):
            c.status = "error"
            c.error = "Upload interrupted; remote outcome is unknown. Local edits and baseline retained."
    # A single-process local app. Serialize writes, pulls and edits so snapshots stay consistent.
    mutation = asyncio.Lock()
    oauth = {}
    challenges = {}
    imports = {}
    callback = os.environ.get(
        "PCE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/callback"
    )
    frontend = os.environ.get("PCE_FRONTEND_ORIGIN", "http://127.0.0.1:5173")
    client_id = os.environ.get("PCE_OAUTH_CLIENT_ID", "personal-chess-explorer")
    allowed_origins = {
        frontend,
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    }

    @app.middleware("http")
    async def local_only(request, call_next):
        if request.url.hostname not in {"localhost", "127.0.0.1", "testserver"}:
            return JSONResponse(
                {"detail": "This application only accepts local hosts"}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins | {
            str(request.base_url).rstrip("/")
        }:
            return JSONResponse({"detail": "Untrusted request origin"}, status_code=403)
        if request.method in {"POST", "PATCH", "DELETE", "PUT"}:
            if (
                request.headers.get("content-type", "").split(";")[0]
                != "application/json"
            ):
                return JSONResponse(
                    {"detail": "JSON requests required"}, status_code=415
                )
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(_, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(LichessError)
    async def lichess_error(_, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    def get_chapter(db, sid, cid):
        c = db.get(Chapter, sid + "/" + cid)
        if not c:
            raise HTTPException(404, "Chapter not found")
        return c

    def check_version(c, expected):
        if digest(c.local) != expected:
            raise ValueError("Chapter changed in another tab. Refresh before editing")

    @app.get("/api/health")
    def health():
        with sessions() as db:
            db.execute(select(Study).limit(1))
        return {"status": "ok", "schema": 1}

    @app.get("/api/auth/status")
    def auth_status():
        return {
            **credentials.status(),
            "write_study_ids": sorted(client.write_study_ids),
        }

    @app.get("/api/auth/connect")
    def connect(write: bool = False):
        state_token, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        scopes = ["study:read"] + (["study:write"] if write else [])
        oauth.clear()
        oauth[state_token] = {
            "verifier": verifier,
            "expires": time.time() + 600,
            "scopes": scopes,
        }
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        response = RedirectResponse(
            "https://lichess.org/oauth?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": callback,
                    "scope": " ".join(scopes),
                    "state": state_token,
                    "code_challenge_method": "S256",
                    "code_challenge": challenge,
                }
            )
        )
        response.set_cookie(
            "pce_oauth", state_token, httponly=True, samesite="lax", max_age=600
        )
        return response

    @app.get("/api/auth/callback")
    async def auth_callback(
        request: Request, state: str = "", code: str = "", error: str = ""
    ):
        pending = oauth.pop(state, None)
        if (
            not pending
            or pending["expires"] < time.time()
            or not secrets.compare_digest(request.cookies.get("pce_oauth", ""), state)
        ):
            raise HTTPException(400, "Invalid or expired OAuth state")
        if error or not code:
            raise HTTPException(400, "Lichess authorization was cancelled")
        async with httpx.AsyncClient(timeout=30, transport=transport) as http:
            try:
                response = await http.post(
                    "https://lichess.org/api/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": pending["verifier"],
                        "redirect_uri": callback,
                        "client_id": client_id,
                    },
                )
            except httpx.RequestError:
                raise LichessError("OAuth token exchange failed") from None
        if response.status_code != 200:
            raise LichessError("OAuth token exchange was rejected; reconnect", 401)
        data = response.json()
        credentials.save(data["access_token"], pending["scopes"], data["expires_in"])
        redirect = RedirectResponse(frontend + "/?connected=1")
        redirect.delete_cookie("pce_oauth")
        return redirect

    @app.post("/api/auth/disconnect")
    async def disconnect():
        credentials.clear()
        return {"authenticated": False}

    @app.get("/api/studies")
    def studies():
        with sessions() as db:
            return [
                study_json(s)
                for s in db.scalars(
                    select(Study).order_by(Study.category, Study.label, Study.id)
                )
            ]

    @app.post("/api/studies")
    async def add_study(body: StudyInput):
        raw = body.url.strip()
        if "://" in raw:
            url = urlparse(raw)
            if (
                url.scheme != "https"
                or url.netloc != "lichess.org"
                or not url.path.startswith("/study/")
            ):
                raise ValueError(
                    "Use a https://lichess.org/study/ URL or eight-character study ID"
                )
            sid = url.path.split("/")[2]
        else:
            sid = raw
        if not ID.fullmatch(sid) or body.side not in {"white", "black", "both"}:
            raise ValueError("Invalid study ID or repertoire side")
        async with mutation:
            with sessions.begin() as db:
                if db.get(Study, sid):
                    raise ValueError("Study is already configured")
                db.add(
                    Study(
                        id=sid,
                        label=body.label,
                        category=body.category,
                        side=body.side,
                        enabled=body.enabled,
                    )
                )
        return {"id": sid}

    @app.patch("/api/studies/{sid}")
    async def update_study(sid: str, body: dict = Body(...)):
        async with mutation:
            with sessions.begin() as db:
                s = db.get(Study, sid)
                if not s:
                    raise HTTPException(404, "Study not found")
                for key in ("label", "category", "side", "enabled"):
                    if key in body:
                        if key == "enabled" and not isinstance(body[key], bool):
                            raise ValueError("Enabled must be boolean")
                        if key != "enabled" and (
                            not isinstance(body[key], str) or len(body[key]) > 100
                        ):
                            raise ValueError("Invalid study label")
                        if key == "side" and body[key] not in {
                            "white",
                            "black",
                            "both",
                        }:
                            raise ValueError("Invalid repertoire side")
                        setattr(s, key, body[key])
        return {"updated": True}

    @app.delete("/api/studies/{sid}")
    async def remove_study(sid: str, body: dict = Body(...)):
        if not body.get("confirmed"):
            raise ValueError(
                "Confirm local removal; cached chapters, edits, history and backups will be removed"
            )
        async with mutation:
            with sessions.begin() as db:
                db.execute(delete(Study).where(Study.id == sid))
        return {"removed_locally": True}

    @app.post("/api/studies/{sid}/refresh")
    async def refresh(sid: str):
        async with mutation:
            with sessions() as db:
                if not db.get(Study, sid):
                    raise HTTPException(404, "Study not found")
            await sync.pull(sid)
        return {"refreshed": sid}

    @app.post("/api/refresh")
    async def refresh_all():
        outcomes = []
        async with mutation:
            with sessions() as db:
                ids = list(db.scalars(select(Study.id).where(Study.enabled.is_(True))))
            for sid in ids:
                try:
                    await sync.pull(sid)
                    outcomes.append({"id": sid, "ok": True})
                except (LichessError, ValueError) as error:
                    outcomes.append({"id": sid, "ok": False, "error": str(error)})
        return outcomes

    @app.get("/api/chapters")
    def chapters(study: str = ""):
        with sessions() as db:
            query = select(Chapter).order_by(Chapter.study_id, Chapter.name)
            if study:
                query = query.where(Chapter.study_id == study)
            return [chapter_json(c) for c in db.scalars(query)]

    @app.post("/api/studies/{sid}/new-chapter/preview")
    async def import_preview(sid: str, body: dict = Body(...)):
        with sessions() as db:
            if not db.get(Study, sid):
                raise HTTPException(404, "Study is not configured")
        game = one(body.get("pgn", ""))
        name = body.get("name", "").strip()
        if not name or len(name) > 100:
            raise ValueError("Chapter name must be 1–100 characters")
        token = secrets.token_urlsafe(32)
        imports[token] = {
            "sid": sid,
            "pgn": serialize(game),
            "name": name,
            "expires": time.time() + 600,
        }
        return {
            "token": token,
            "pgn": serialize(game),
            "name": name,
            "can_write": client.can_write(sid),
        }

    @app.post("/api/studies/{sid}/new-chapter/push")
    async def import_push(sid: str, body: dict = Body(...)):
        if not body.get("confirmed"):
            raise ValueError("Confirm adding this chapter on Lichess")
        pending = imports.pop(body.get("token", ""), None)
        if not pending or pending["sid"] != sid or pending["expires"] < time.time():
            raise ValueError("Import preview expired")
        async with mutation:
            client.authorize_write(sid)
            with sessions.begin() as db:
                operation = Operation(
                    chapter_id=sid + "/new",
                    state="uploading",
                    detail="New chapter import",
                )
                db.add(operation)
            try:
                response = await client.import_pgn(sid, pending["pgn"], pending["name"])
                chapters = response.get("chapters", [])
                if (
                    response.get("error")
                    or len(chapters) != 1
                    or not ID.fullmatch(chapters[0].get("id", ""))
                ):
                    raise LichessError(
                        "Chapter import response is uncertain; refresh the study before trying again"
                    )
                cid = chapters[0]["id"]
                remote = one(await client.chapter(sid, cid))
                if chapter_identity(remote, sid) != cid or semantic(
                    remote, False
                ) != semantic(one(pending["pgn"]), False):
                    raise LichessError(
                        "Imported chapter verification failed; inspect Lichess before retrying"
                    )
                await sync.pull(sid)
                with sessions.begin() as db:
                    db.get(Operation, operation.id).state = "synced"
                return {"created": sid + "/" + cid}
            except Exception:
                with sessions.begin() as db:
                    op = db.get(Operation, operation.id)
                    op.state = "error"
                    op.detail = "Import failed or outcome is uncertain. Refresh Lichess before retrying to avoid duplicate chapters."
                raise

    @app.get("/api/chapters/{sid}/{cid}")
    def chapter(sid: str, cid: str):
        with sessions() as db:
            c = get_chapter(db, sid, cid)
            return {**chapter_json(c, True), "hash": digest(c.local)}

    @app.get("/api/chapters/{sid}/{cid}/export")
    def export(sid: str, cid: str):
        with sessions() as db:
            return Response(
                get_chapter(db, sid, cid).local, media_type="application/x-chess-pgn"
            )

    @app.post("/api/chapters/{sid}/{cid}/edit")
    async def edit_chapter(sid: str, cid: str, body: EditInput):
        async with mutation:
            with sessions.begin() as db:
                c = get_chapter(db, sid, cid)
                check_version(c, body.expected_hash)
                if body.action in {"undo", "redo"}:
                    source, destination = (
                        ("undo", "redo") if body.action == "undo" else ("redo", "undo")
                    )
                    history = json.loads(getattr(c, source))
                    if not history:
                        raise ValueError("History is empty")
                    setattr(
                        c,
                        destination,
                        json.dumps(
                            (json.loads(getattr(c, destination)) + [c.local])[-100:]
                        ),
                    )
                    c.local = history.pop()
                    setattr(c, source, json.dumps(history))
                else:
                    updated = edit(
                        c.local,
                        body.action,
                        body.path,
                        **body.model_dump(
                            exclude={"action", "path", "expected_hash"},
                            exclude_none=True,
                        ),
                    )
                    c.undo = json.dumps((json.loads(c.undo) + [c.local])[-100:])
                    c.redo = "[]"
                    c.local = updated
                c.status = (
                    "conflict"
                    if c.deleted
                    else state(c.base, c.local, c.remote or c.base)
                )
                c.error = None
                reindex(db, c)
        return chapter(sid, cid)

    @app.post("/api/chapters/{sid}/{cid}/preview")
    async def preview(sid: str, cid: str):
        async with mutation:
            return await sync.preview(sid + "/" + cid)

    @app.post("/api/chapters/{sid}/{cid}/push")
    async def push(sid: str, cid: str, body: PushInput):
        async with mutation:
            return await sync.push(
                sid + "/" + cid, body.token, body.overwrite, body.confirmed
            )

    @app.post("/api/chapters/{sid}/{cid}/resolve")
    async def resolve(sid: str, cid: str, body: dict = Body(...)):
        if not body.get("confirmed"):
            raise ValueError("Explicit confirmation required")
        async with mutation:
            with sessions.begin() as db:
                c = get_chapter(db, sid, cid)
                check_version(c, body.get("expected_hash", ""))
                if body.get("choice") == "remote":
                    remote = serialize(one(await client.chapter(sid, cid)))
                    if chapter_identity(one(remote), sid) != cid:
                        raise ValueError("Remote chapter identity mismatch")
                    db.add(Backup(chapter_id=c.id, pgn=c.local))
                    accept_remote(db, c, remote)
                elif body.get("choice") == "manual":
                    game = one(body.get("pgn", ""))
                    current = one(c.local)
                    if game.board().fen() != current.board().fen():
                        raise ValueError("Starting position cannot change")
                    for k in {
                        "StudyName",
                        "ChapterName",
                        "ChapterURL",
                        "Site",
                        "Annotator",
                        "UTCDate",
                        "UTCTime",
                        "Variant",
                        "FEN",
                        "SetUp",
                        "Orientation",
                    }:
                        if k in current.headers:
                            game.headers[k] = current.headers[k]
                        else:
                            game.headers.pop(k, None)
                    c.undo = json.dumps((json.loads(c.undo) + [c.local])[-100:])
                    c.redo = "[]"
                    c.local = serialize(game)
                    c.status = state(c.base, c.local, c.remote or c.base)
                    reindex(db, c)
                else:
                    raise ValueError(
                        "Choose remote or manual. Keeping local requires a fresh push preview"
                    )
        return chapter(sid, cid)

    @app.get("/api/backups")
    def backups():
        with sessions() as db:
            return [
                {"id": b.id, "chapter_id": b.chapter_id, "created": b.created}
                for b in db.scalars(select(Backup).order_by(Backup.id.desc()))
            ]

    @app.get("/api/backups/{bid}")
    def backup(bid: int):
        with sessions() as db:
            b = db.get(Backup, bid)
            if not b:
                raise HTTPException(404, "Backup not found")
            return Response(b.pgn, media_type="application/x-chess-pgn")

    @app.post("/api/backups/{bid}/restore")
    async def restore(bid: int, body: dict = Body(...)):
        if not body.get("confirmed"):
            raise ValueError("Confirm restoration to local pending edits")
        async with mutation:
            with sessions.begin() as db:
                b = db.get(Backup, bid)
                if not b:
                    raise HTTPException(404, "Backup not found")
                c = db.get(Chapter, b.chapter_id)
                check_version(c, body.get("expected_hash", ""))
                c.undo = json.dumps((json.loads(c.undo) + [c.local])[-100:])
                c.redo = "[]"
                c.local = b.pgn
                c.status = state(c.base, c.local, c.remote or c.base)
                reindex(db, c)
        return {"restored_locally": True}

    @app.get("/api/snapshots/{sid}/{cid}")
    def snapshots(sid: str, cid: str):
        with sessions() as db:
            return [
                {"id": s.id, "hash": s.hash, "created": s.created, "pgn": s.pgn}
                for s in db.scalars(
                    select(Snapshot)
                    .where(Snapshot.chapter_id == sid + "/" + cid)
                    .order_by(Snapshot.id.desc())
                )
            ]

    @app.get("/api/operations")
    def operations():
        with sessions() as db:
            return [
                {
                    "id": o.id,
                    "chapter_id": o.chapter_id,
                    "state": o.state,
                    "detail": o.detail,
                    "created": o.created,
                }
                for o in db.scalars(
                    select(Operation).order_by(Operation.id.desc()).limit(100)
                )
            ]

    def occurrence_query(study="", category="", chapter="", side="", opening=""):
        query = (
            select(Occurrence, Chapter, Study)
            .join(Chapter, Occurrence.chapter_id == Chapter.id)
            .join(Study, Chapter.study_id == Study.id)
            .where(Study.enabled.is_(True), Chapter.deleted.is_(False))
        )
        if study:
            query = query.where(Study.id == study)
        if category:
            query = query.where(Study.category == category)
        if chapter:
            query = query.where(Chapter.id == chapter)
        if side in {"white", "black"}:
            query = query.where(Study.side.in_([side, "both"]))
        if opening:
            # Opening tag is chapter content; using a plain text contains filter is sufficient locally.
            query = query.where(Chapter.local.contains('[Opening "' + opening))
        return query

    def reference(o, c, s):
        return {
            "study_id": s.id,
            "study": s.label or s.title or s.id,
            "chapter_id": c.id,
            "chapter": c.name,
            "category": s.category,
            "path": o.path,
            "fen": o.fen,
            "comment": o.comment,
            "nags": json.loads(o.nags),
            "status": c.status,
            "url": f"https://lichess.org/study/{s.id}/{c.remote_id}",
        }

    @app.get("/api/explorer")
    def explorer(
        fen: str = chess.STARTING_FEN,
        study: str = "",
        category: str = "",
        chapter: str = "",
        side: str = "",
        opening: str = "",
    ):
        key = position_key(fen)
        with sessions() as db:
            rows = list(
                db.execute(
                    occurrence_query(study, category, chapter, side, opening).where(
                        Occurrence.key == key
                    )
                )
            )
            grouped = {}
            for o, c, s in rows:
                for move in json.loads(o.continuations):
                    entry = grouped.setdefault(
                        move["uci"],
                        {"uci": move["uci"], "san": move["san"], "references": []},
                    )
                    entry["references"].append({**reference(o, c, s), **move})
            for entry in grouped.values():
                entry["studies"] = len({r["study_id"] for r in entry["references"]})
                entry["chapters"] = len({r["chapter_id"] for r in entry["references"]})
                entry["occurrences"] = len(entry["references"])
            return {
                "position": key,
                "occurrences": [reference(*r) for r in rows],
                "moves": list(grouped.values()),
            }

    @app.get("/api/search")
    def search(
        q: str, study: str = "", category: str = "", chapter: str = "", side: str = ""
    ):
        with sessions() as db:
            results = []
            query = occurrence_query(study, category, chapter, side)
            term = q.strip().lower()
            try:
                query = query.where(Occurrence.key == position_key(q))
                is_fen = True
            except ValueError:
                is_fen = False
            if not is_fen:
                escaped = (
                    term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                query = query.where(
                    or_(
                        *(
                            func.lower(column).contains(term, autoescape=True)
                            for column in (
                                Study.title,
                                Study.label,
                                Study.category,
                                Chapter.name,
                                Occurrence.comment,
                                Occurrence.san,
                                Occurrence.path,
                                Occurrence.fen,
                            )
                        ),
                        func.lower(Chapter.local).like(
                            '%[opening "%' + escaped + '%"]%', escape="\\"
                        ),
                    )
                )
            for o, c, s in db.execute(query.limit(100)):
                results.append(reference(o, c, s))
            return results

    @app.get("/api/training/next")
    def training_next(
        study: str = "", category: str = "", chapter: str = "", side: str = ""
    ):
        with sessions() as db:
            choices = []
            for o, c, s in db.execute(occurrence_query(study, category, chapter, side)):
                moves = json.loads(o.continuations)
                if not moves or (
                    side in {"white", "black"}
                    and chess.Board(o.fen).turn != (side == "white")
                ):
                    continue
                latest = db.scalar(
                    select(Training)
                    .where(Training.chapter_id == c.id, Training.path == o.path)
                    .order_by(Training.id.desc())
                    .limit(1)
                )
                due = latest.due if latest else ""
                if due and due > now():
                    continue
                choices.append((due, o, c, s))
            if not choices:
                return {"done": True}
            _, o, c, s = min(choices, key=lambda r: (r[0], r[2].id, r[1].id))
            token = secrets.token_urlsafe(24)
            challenges[token] = {
                "chapter": c.id,
                "path": o.path,
                "hash": digest(c.local),
                "expires": time.time() + 1800,
            }
            for stale in [
                k for k, v in challenges.items() if v["expires"] < time.time()
            ]:
                del challenges[stale]
            # Deliberately withhold prepared continuations and revealing comments.
            return {
                "token": token,
                "fen": o.fen,
                "chapter_id": c.id,
                "chapter": c.name,
                "study": s.label or s.title,
                "done": False,
            }

    @app.post("/api/training/answer")
    async def training_answer(body: dict = Body(...)):
        challenge = challenges.pop(body.get("token", ""), None)
        if not challenge or challenge["expires"] < time.time():
            raise ValueError("Training exercise expired")
        async with mutation:
            with sessions.begin() as db:
                c = db.get(Chapter, challenge["chapter"])
                if not c or digest(c.local) != challenge["hash"]:
                    raise ValueError("Chapter changed; load another exercise")
                o = db.scalar(
                    select(Occurrence).where(
                        Occurrence.chapter_id == c.id,
                        Occurrence.path == challenge["path"],
                    )
                )
                if not o:
                    raise ValueError("Position no longer exists")
                moves = json.loads(o.continuations)
                correct = body.get("uci") in {m["uci"] for m in moves}
                latest = db.scalar(
                    select(Training)
                    .where(Training.chapter_id == c.id, Training.path == o.path)
                    .order_by(Training.id.desc())
                    .limit(1)
                )
                interval = (
                    min(60, (latest.interval * 2 if latest and latest.correct else 1))
                    if correct
                    else 0
                )
                due = (
                    datetime.now(timezone.utc)
                    + (timedelta(days=interval) if correct else timedelta(minutes=10))
                ).isoformat()
                db.add(
                    Training(
                        chapter_id=c.id,
                        path=o.path,
                        correct=correct,
                        interval=interval,
                        due=due,
                    )
                )
                return {
                    "correct": correct,
                    "moves": moves,
                    "comment": o.comment,
                    "due": due,
                }

    @app.get("/api/training/progress")
    def progress():
        with sessions() as db:
            rows = list(db.scalars(select(Training)))
            return {
                "attempts": len(rows),
                "correct": sum(r.correct for r in rows),
                "recent": [
                    {"chapter_id": r.chapter_id, "correct": r.correct, "due": r.due}
                    for r in rows[-20:][::-1]
                ],
            }

    # Production build is served on the same loopback origin; Vite proxies /api in development.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
