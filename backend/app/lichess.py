"""Only official Lichess study and OAuth endpoints. Never retry uncertain writes."""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx


class LichessError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class Credentials:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text())
        if data.get("expires", 0) <= time.time():
            return {}
        return data

    def save(self, token, scopes, expires_in):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(
                {"token": token, "scopes": scopes, "expires": time.time() + expires_in},
                handle,
            )
        os.replace(temporary, self.path)
        os.chmod(self.path, 0o600)

    def clear(self):
        self.path.unlink(missing_ok=True)

    def status(self):
        data = self.read()
        return {
            "authenticated": bool(data),
            "scopes": data.get("scopes", []),
            "write": "study:write" in data.get("scopes", []),
        }


class Lichess:
    def __init__(self, credentials, transport=None, write_study_ids=None):
        self.credentials = credentials
        self.transport = transport
        self.gate = asyncio.Lock()
        self.write_study_ids = set(write_study_ids or [])

    def can_write(self, sid):
        return self.credentials.status()["write"] and sid in self.write_study_ids

    def authorize_write(self, sid):
        if not self.credentials.status()["write"]:
            raise LichessError(
                "Connect Lichess with study:write permission before uploading", 403
            )
        if sid not in self.write_study_ids:
            raise LichessError(
                "Live write-back is disabled for this study. Enable only a disposable test study through PCE_WRITE_STUDY_IDS first; verify its round-trip before enabling important studies",
                403,
            )

    async def request(self, method, path, **kwargs):
        async with self.gate:
            data = self.credentials.read()
            headers = {
                "User-Agent": "PersonalChessExplorer/0.1 (local repertoire tool)"
            }
            if data:
                headers["Authorization"] = "Bearer " + data["token"]
            async with httpx.AsyncClient(
                base_url="https://lichess.org",
                timeout=30,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                for attempt in range(2):
                    try:
                        response = await client.request(
                            method, path, headers=headers, **kwargs
                        )
                    except httpx.RequestError:
                        raise LichessError(
                            "Lichess network request failed or timed out; no write retry was attempted"
                        ) from None
                    if response.status_code == 429:
                        # Lichess recommends waiting at least one minute after 429.
                        if method == "GET" and attempt == 0:
                            await asyncio.sleep(
                                max(
                                    60,
                                    min(
                                        120,
                                        int(response.headers.get("Retry-After", "60"))
                                        if response.headers.get(
                                            "Retry-After", "60"
                                        ).isdigit()
                                        else 60,
                                    ),
                                )
                            )
                            continue
                        raise LichessError(
                            "Lichess rate limit reached. Wait at least one minute before retrying",
                            429,
                        )
                    if response.status_code in (401, 403):
                        if response.status_code == 401:
                            self.credentials.clear()
                        raise LichessError(
                            "Lichess authorization denied; reconnect or check study permissions",
                            response.status_code,
                        )
                    if response.status_code == 404:
                        raise LichessError(
                            "Study or chapter not found or inaccessible", 404
                        )
                    if response.is_error or response.is_redirect:
                        raise LichessError(
                            f"Lichess returned HTTP {response.status_code}; local edits are retained"
                        )
                    return response

    async def study(self, sid):
        return (
            await self.request(
                "GET",
                f"/api/study/{sid}.pgn",
                params={"clocks": "true", "comments": "true", "variations": "true"},
            )
        ).text

    async def chapter(self, sid, cid):
        return (
            await self.request(
                "GET",
                f"/api/study/{sid}/{cid}.pgn",
                params={"clocks": "true", "comments": "true", "variations": "true"},
            )
        ).text

    async def moves(self, sid, cid, pgn):
        self.authorize_write(sid)
        await self.request("POST", f"/api/study/{sid}/{cid}/moves", data={"pgn": pgn})

    async def tags(self, sid, cid, pgn):
        self.authorize_write(sid)
        await self.request("POST", f"/api/study/{sid}/{cid}/tags", data={"pgn": pgn})

    async def import_pgn(self, sid, pgn, name):
        self.authorize_write(sid)
        return (
            await self.request(
                "POST", f"/api/study/{sid}/import-pgn", data={"pgn": pgn, "name": name}
            )
        ).json()
