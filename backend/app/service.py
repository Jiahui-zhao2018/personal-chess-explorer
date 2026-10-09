import difflib
import json
import secrets
import time

from sqlalchemy import delete, select

from .db import Backup, Chapter, Occurrence, Operation, Position, Snapshot, Study, now
from .lichess import LichessError
from .pgn import (
    IDENTITY_TAGS,
    chapter_identity,
    digest,
    one,
    parse,
    position_key,
    semantic,
    serialize,
    walk,
)


def state(base, local, remote):
    b, l, r = map(digest, (base, local, remote))
    if l == r:
        return "synced"
    if b == r:
        return "pending"
    if b == l:
        return "remote_changed"
    return "conflict"


def reindex(db, chapter):
    db.execute(delete(Occurrence).where(Occurrence.chapter_id == chapter.id))
    if chapter.deleted:
        return
    for node, path in walk(one(chapter.local)):
        board = node.board()
        key = position_key(board.fen())
        if db.get(Position, key) is None:
            db.add(Position(key=key))
            db.flush()
        db.add(
            Occurrence(
                key=key,
                chapter_id=chapter.id,
                path=path,
                fen=board.fen(),
                san=node.san() if node.parent else "Start",
                comment=node.comment,
                nags=json.dumps(sorted(node.nags)),
                continuations=json.dumps(
                    [
                        {
                            "uci": v.move.uci(),
                            "san": board.san(v.move),
                            "comment": v.comment,
                            "nags": sorted(v.nags),
                            "path": (path + "/" + v.move.uci()).lstrip("/"),
                        }
                        for v in node.variations
                    ]
                ),
            )
        )


def snapshot(db, chapter, pgn):
    db.add(Snapshot(chapter_id=chapter.id, pgn=pgn, hash=digest(pgn)))


def accept_remote(db, chapter, remote):
    snapshot(db, chapter, remote)
    chapter.base = chapter.local = remote
    chapter.remote = remote
    chapter.status = "synced"
    chapter.deleted = False
    chapter.undo = chapter.redo = "[]"
    chapter.error = None
    reindex(db, chapter)


class Sync:
    def __init__(self, sessions, client):
        self.sessions = sessions
        self.client = client
        self.previews = {}

    async def pull(self, sid):
        # Parse and validate every identity before modifying persistent state.
        try:
            source = await self.client.study(sid)
            games = parse(source)
            incoming = [(chapter_identity(g, sid), g) for g in games]
            if len({cid for cid, _ in incoming}) != len(incoming):
                raise ValueError("Duplicate chapter identities in export")
        except (LichessError, ValueError) as error:
            with self.sessions.begin() as db:
                study = db.get(Study, sid)
                if study:
                    study.error = str(error)
            raise
        with self.sessions.begin() as db:
            study = db.get(Study, sid)
            if study is None:
                raise ValueError("Study is not configured")
            study.title = games[0].headers.get(
                "StudyName", games[0].headers.get("Event", sid)
            )
            seen = set()
            for cid, game in incoming:
                key = sid + "/" + cid
                seen.add(key)
                remote = serialize(game)
                chapter = db.get(Chapter, key)
                if chapter is None:
                    chapter = Chapter(
                        id=key,
                        study_id=sid,
                        remote_id=cid,
                        name=game.headers.get(
                            "ChapterName", game.headers.get("Event", cid)
                        ),
                        base=remote,
                        local=remote,
                        remote=remote,
                    )
                    db.add(chapter)
                    db.flush()
                    snapshot(db, chapter, remote)
                    reindex(db, chapter)
                else:
                    chapter.name = game.headers.get(
                        "ChapterName", game.headers.get("Event", cid)
                    )
                    current = state(chapter.base, chapter.local, remote)
                    chapter.remote = remote
                    chapter.deleted = False
                    if current in {"synced", "remote_changed"}:
                        if digest(chapter.base) != digest(remote) or digest(
                            chapter.local
                        ) != digest(remote):
                            accept_remote(db, chapter, remote)
                        else:
                            chapter.status = "synced"
                    else:
                        chapter.status = current
                    chapter.error = None
                chapter.fetched = now()
            for chapter in db.scalars(select(Chapter).where(Chapter.study_id == sid)):
                if chapter.id not in seen:
                    chapter.deleted = True
                    chapter.status = (
                        "conflict"
                        if digest(chapter.local) != digest(chapter.base)
                        else "remote_changed"
                    )
                    chapter.error = (
                        "Chapter was removed remotely. Local snapshots are retained."
                    )
                    reindex(db, chapter)
            study.fetched = now()
            study.error = None

    async def preview(self, key):
        with self.sessions() as db:
            chapter = db.get(Chapter, key)
            if chapter is None:
                raise ValueError("Chapter not found")
            if chapter.deleted:
                raise ValueError("Remote chapter is deleted; cannot overwrite it")
            remote = serialize(
                one(await self.client.chapter(chapter.study_id, chapter.remote_id))
            )
            if chapter_identity(one(remote), chapter.study_id) != chapter.remote_id:
                raise ValueError("Remote chapter identity mismatch")
            status = state(chapter.base, chapter.local, remote)
            chapter.remote = remote
            chapter.status = status
            db.commit()
            token = secrets.token_urlsafe(32)
            self.previews = {
                k: v for k, v in self.previews.items() if v["expires"] > time.time()
            }
            self.previews[token] = {
                "key": key,
                "local": digest(chapter.local),
                "remote": digest(remote),
                "expires": time.time() + 600,
                "status": status,
            }

            def diff(a, b, label):
                return "\n".join(
                    difflib.unified_diff(
                        a.splitlines(),
                        b.splitlines(),
                        fromfile="baseline",
                        tofile=label,
                        lineterm="",
                    )
                )

            return {
                "token": token,
                "status": status,
                "local_diff": diff(chapter.base, chapter.local, "local"),
                "remote_diff": diff(chapter.base, remote, "remote"),
                "upload_diff": "\n".join(
                    difflib.unified_diff(
                        remote.splitlines(),
                        chapter.local.splitlines(),
                        fromfile="remote",
                        tofile="upload",
                        lineterm="",
                    )
                ),
                "base": chapter.base,
                "local": chapter.local,
                "remote": remote,
                "can_write": self.client.can_write(chapter.study_id),
                "warning": "Moves replace the entire chapter. Tags are a separate non-atomic request. Lichess has no compare-and-swap: another edit may occur between the final fetch and upload. PGN does not preserve all Lichess-specific data.",
            }

    async def push(self, key, token, overwrite, confirmed):
        if not confirmed:
            raise ValueError("Explicit confirmation is required")
        preview = self.previews.pop(token, None)
        if not preview or preview["key"] != key or preview["expires"] < time.time():
            raise ValueError("Preview expired. Generate a fresh preview")
        with self.sessions() as db:
            chapter = db.get(Chapter, key)
            if chapter is None or chapter.deleted:
                raise ValueError("Chapter is unavailable")
            self.client.authorize_write(chapter.study_id)
            local = chapter.local
            if digest(local) != preview["local"]:
                raise ValueError("Local content changed after preview")
            # Immediately before submission; do not rely on an earlier preview fetch.
            remote = serialize(
                one(await self.client.chapter(chapter.study_id, chapter.remote_id))
            )
            if chapter_identity(one(remote), chapter.study_id) != chapter.remote_id:
                raise ValueError("Remote chapter identity mismatch")
            if digest(remote) != preview["remote"]:
                chapter.remote = remote
                chapter.status = state(chapter.base, local, remote)
                db.commit()
                raise ValueError(
                    "Remote changed after preview; generate a fresh preview"
                )
            current = state(chapter.base, local, remote)
            if current in {"conflict", "remote_changed"} and not overwrite:
                raise ValueError(
                    "Remote changes require explicit overwrite confirmation or manual resolution"
                )
            if digest(local) == digest(remote):
                accept_remote(db, chapter, remote)
                db.commit()
                return {"status": "synced", "uploaded": False}
            # Backup is durable BEFORE the first outbound write.
            backup = Backup(chapter_id=key, pgn=remote)
            operation = Operation(chapter_id=key, state="uploading")
            db.add_all([backup, operation])
            chapter.status = "uploading"
            db.commit()
            try:
                remote_game, local_game = one(remote), one(local)
                if semantic(remote_game, False) != semantic(local_game, False):
                    await self.client.moves(chapter.study_id, chapter.remote_id, local)
                old_tags = {
                    k: v
                    for k, v in remote_game.headers.items()
                    if k not in IDENTITY_TAGS
                }
                new_tags = {
                    k: v
                    for k, v in local_game.headers.items()
                    if k not in IDENTITY_TAGS
                }
                changed = {
                    k: new_tags.get(k, "")
                    for k in old_tags.keys() | new_tags.keys()
                    if old_tags.get(k) != new_tags.get(k)
                }
                if changed:
                    # Values are validated by edit(); escaping is retained for imported PGNs.
                    tags = "\n".join(
                        "["
                        + k
                        + ' "'
                        + v.replace("\\", "\\\\").replace('"', '\\"')
                        + '"]'
                        for k, v in sorted(changed.items())
                    )
                    await self.client.tags(chapter.study_id, chapter.remote_id, tags)
                verified = serialize(
                    one(await self.client.chapter(chapter.study_id, chapter.remote_id))
                )
                if chapter_identity(
                    one(verified), chapter.study_id
                ) != chapter.remote_id or digest(verified) != digest(local):
                    chapter.remote = verified
                    raise LichessError(
                        "Post-upload verification failed. Baseline and local edits retained; inspect backup and remote before retrying"
                    )
                accept_remote(db, chapter, verified)
                operation.state = "synced"
                db.commit()
                return {"status": "synced", "uploaded": True, "backup_id": backup.id}
            except Exception as error:
                chapter.status = operation.state = "error"
                chapter.error = operation.detail = (
                    str(error)
                    if isinstance(error, (LichessError, ValueError))
                    else "Unexpected synchronization failure"
                )
                db.commit()
                raise
