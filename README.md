# Personal Chess Explorer

A local repertoire explorer built with React, TypeScript, Vite, Tailwind CSS,
react-chessboard and chess.js, backed by FastAPI, python-chess, SQLAlchemy and SQLite.
**Only explicitly configured Lichess Studies supply repertoire data.** There are no
game-history imports, master databases, win rates, or paid services.

## Run locally

Requirements: Bash 3.2+ (no `wait -n` required), Python 3.11+ and Node 20.19+, 22.12+, or 24+. Tested here with Python
3.12 and Node 24. Use the existing checkout; a separate Git worktree is unnecessary.

```bash
bash scripts/install.sh
bash scripts/dev.sh
```

Open `http://127.0.0.1:5173` in your local browser. The backend listens on port 8000;
Vite proxies `/api` to it. The backend binds to `127.0.0.1:8000`; the frontend
binds to `0.0.0.0:5173` so the authenticated cloud preview proxy can connect.
Stop both with Ctrl+C. Set `PCE_DEV_HOST=127.0.0.1` for loopback-only frontend access.
The startup supervisor uses portable PID polling and single-PID `wait`, not
`wait -n`. If either service exits, its status is reported and the other is
stopped. Ctrl+C/SIGTERM stop both; an unresponsive child is killed after a
five-second grace period. Supervisor regression tests run under Bash and POSIX sh.
Use **Studies → Add & fetch** to add a study URL or its eight-character ID.
Public studies work without authentication. No study is imported automatically.

### Cloud web preview

Keep `bash scripts/dev.sh` running and select **port 5173** in the cloud preview.
If the preview forwards an external Host, start with its exact origin configured:

```bash
PCE_FRONTEND_ORIGIN=https://your-preview-host.example bash scripts/dev.sh
```

This permits that hostname in Vite and that origin in the backend. Vite rewrites
the proxied API Host to the loopback backend with `changeOrigin: true`. Additional
trusted hostnames can be supplied through `PCE_PREVIEW_HOSTS`; all-host trust is
not enabled. Use only an authenticated preview: the workspace has no application
login protecting cached private study data from other visitors. OAuth callback
configuration remains separate in `PCE_OAUTH_REDIRECT_URI`.

For a blank preview, check that both servers are running, port 5173 is selected,
and Network shows HTML, `/src/main.tsx`, module assets and `/api/health` returning
200. An unknown hostname is rejected rather than silently exposing the workspace.
The regression test `PCE_CHROMIUM_PATH=/usr/bin/chromium npm run test:preview`
(in `frontend`) exercises the dev server under an external hostname, API editing,
and continued rejection of untrusted hosts/origins using temporary fixture data.

For a production build served by FastAPI alone:

```bash
cd frontend && npm run build && cd ..
export PCE_FRONTEND_ORIGIN=http://127.0.0.1:8000
.venv/bin/python -m uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 8000 --no-access-log
```

Run **one backend process/worker**. In-memory synchronization locks, short-lived
review tokens, training challenges and OAuth state are intentionally single-process.
This is a local, single-user application, not a public multi-user deployment.

## Implemented

- Manage an explicit study list: enable/disable, labels, categories, repertoire
  color, local removal, individual/all-enabled refresh and last successful pull.
- Download all chapters through the official Lichess study export API, including
  variations, comments and clocks. Validate all chapters before a pull commits.
- Preserve chapter identity through exported `ChapterURL` (legacy `Site` fallback).
  Missing/ambiguous identities fail closed rather than creating guessed IDs.
- Parse full, nested PGN trees, custom standard-chess starting FEN, comments,
  starting comments, NAGs, tags and PGN clock/evaluation directives.
- Merge positions across chapters and move-order transpositions. Identity uses
  board arrangement, side to move, castling rights and **legal** en passant rights;
  move counters are excluded. Every chapter occurrence remains independent.
- Drag/click a legal move, select a recorded continuation, choose promotions,
  flip the board, navigate with arrow keys, inspect all source references, jump
  to FEN, search and filter by study/chapter/category/color/opening tag.
- Edit one selected chapter: add/extend/delete variations, promote a mainline,
  reorder children, edit comments/NAGs/tags, and undo/redo (100 local steps).
  UCI paths identify nodes independently of variation order.
- Compare baseline/local/remote versions, retain unsynchronized edits on pull,
  detect remote deletion and concurrent changes, show textual diffs, resolve
  manually or keep remote, and require explicit consent for remote overwrite.
- Back up pre-upload remote PGN, prevent simultaneous uploads/edits, re-fetch
  immediately before writing, verify after writing and preserve the baseline
  when verification fails. Backup restoration creates **local pending edits**.
- Create one new chapter from validated PGN using a separate confirmed import.
- Train only imported lines; accept all prepared alternatives in the selected
  chapter, reveal notes after answering, and record local spaced review history.
  Correct answers review in 1, 2, 4…60 days; incorrect answers in 10 minutes.
- SQLite schema migration v1, chapter snapshot history, synchronization operation
  history and interrupted-upload recovery.

The explorer's counts are **unique studies, unique chapters, and occurrences**,
not game frequencies. Local edits appear in the cache with a pending status;
Lichess remains the canonical source until a verified upload succeeds.

## Authentication

In **Settings**, choose **Connect read only** or **Connect read & write**.
OAuth Authorization Code + PKCE uses the documented Lichess `/oauth` and
`/api/token` endpoints, an HttpOnly state cookie and a ten-minute callback state.
Read-only requests ask only for `study:read`; writes additionally ask for
`study:write`. The logged-in account must also have access/edit rights on the study.
Unlisted/private studies require the authenticated account's access.

The default callback is `http://127.0.0.1:8000/api/auth/callback`. Use the same host
consistently so the state cookie is returned. `.env.example` lists supported
configuration variables; to use a local `.env`, explicitly export its contents in
your shell before starting (the application does not load it automatically).

Tokens never enter frontend state, responses, logs or SQLite. They are stored in
`backend/data/credentials.json` with permissions **0600**, inside a **0700** data
directory. This is owner-only local file storage, not encryption or an OS keychain.
Protect the machine/account and its filesystem backups. Do not commit or share
the data directory: it can contain private study PGNs. Expired credentials are
treated as disconnected; HTTP 401 clears credentials. Disconnect removes the
local token without deleting Lichess data. Revoke it in Lichess account settings
if you want server-side revocation.

`PCE_DATA_DIR` can point to another private local directory. Ordinary JSON APIs
require trusted loopback hosts/origins, and mutations require JSON to prevent
cross-site form submission. Keep the backend on loopback and do not expose the
frontend through an unauthenticated public tunnel. Access logging is disabled by the startup commands so OAuth
callback query strings are not recorded.

## Write-back safety and verified API contract

**Live writes are disabled by default, even with a write-scoped token.**
`PCE_WRITE_STUDY_IDS` is a comma-separated allowlist of studies that the backend
may write. First enable only a disposable study you own and explicitly authorize:

```bash
export PCE_WRITE_STUDY_IDS=YOUR8ID0
bash scripts/dev.sh
```

Before enabling an important study, use the disposable study to verify nested
variations, comments, NAGs, clocks/evaluations, your actual tags and starting FEN;
inspect both the resulting Lichess chapter and the downloaded PGN. Automated
tests mock Lichess and **do not establish live round-trip behavior**. No live
remote write was performed during implementation.

The API contract was checked against the official OpenAPI files in
[lichess-org/api](https://github.com/lichess-org/api/tree/master/doc/specs/tags/studies)
and [Lichess API documentation](https://lichess.org/api):

| Operation | Official endpoint | Behavior |
| --- | --- | --- |
| Pull study | `GET /api/study/{studyId}.pgn` | Export all chapters; request comments, variations and clocks |
| Re-check chapter | `GET /api/study/{studyId}/{chapterId}.pgn` | Obtain current chapter before/after writes |
| Replace moves | `POST /api/study/{studyId}/{chapterId}/moves` | Form field `pgn`; replaces the whole move tree; ignores tags |
| Update tags | `POST /api/study/{studyId}/{chapterId}/tags` | Form field `pgn`; omitted tags remain; empty values delete tags |
| New chapter | `POST /api/study/{studyId}/import-pgn` | Form fields `pgn`, `name`; creates a chapter, never replaces one |

Upload reviews expire after ten minutes and are single-use. Both local and remote
hashes must still match the reviewed versions. Conflict/remote-only differences
require an additional explicit overwrite acknowledgement. Backups are committed
before any remote write. A no-change upload performs no remote writes.

Moves and tags are **two separate, non-transactional requests**. A partial update
is possible. Lichess has no atomic compare-and-swap; another user can edit between
the final fetch and write. The application cannot eliminate that race. HTTP errors,
timeouts or a different post-write PGN retain pending edits, the old baseline and
backup; inspect the remote chapter before retrying. Writes are never automatically
retried. Read requests after HTTP 429 wait at least 60 seconds and retry once.

PGN round-trips preserve the **supported standard PGN content** tested here, not
every Lichess-specific property. Formatting is canonicalized. Interactive lesson
settings, chapter permissions, embedded media, study metadata and other data not
represented in exported PGN are not promised to survive move-tree replacement.
Study identity, variant, orientation and starting-FEN tags are immutable locally.
Only standard chess is supported; variant studies are rejected. Custom edited tag
values containing quotes, backslashes or newlines are rejected conservatively.
Unsupported tags may be rejected/normalized by Lichess; failed verification is
reported rather than claimed as success.

There is no automatic concurrent merge. All concurrent edits require review, even
when a human could merge them safely. A remotely removed chapter is retained
locally for inspection but excluded from the explorer and blocked from upload.
Removing a configured study is local-only, and explicitly confirms removal of its
cached chapters, pending edits, snapshots, training history and backups.

## Storage and modules

`backend/app/db.py` defines `configured_studies`, `study_chapters`,
`chapter_snapshots`, `positions`, `position_occurrences`, `sync_operations`,
`sync_backups` and `training_results`. Pending local PGN and last confirmed baseline
are separate chapter fields. Full trees are stored per chapter, not per position.
Occurrences reference a chapter and an exact UCI path. Position lookup uses a
SQLite index. Search filters run in SQL with a 100-result cap.

`backend/app/migrations.py` applies the initial schema and tracks
`PRAGMA user_version=1`; repeat startup is idempotent, and unknown future versions
are rejected. SQLite uses foreign keys, WAL and a busy timeout. Copy the database
and credential directory only when the app is stopped, or use SQLite's backup
API; copying only the live `.sqlite` file can omit WAL data.

| File | Purpose |
| --- | --- |
| `backend/app/lichess.py` | Official API client, permission checks, credentials and rate limiting |
| `backend/app/pgn.py` | Strict PGN validation, trees, stable nodes, editing and semantic hashes |
| `backend/app/service.py` | Indexed occurrences, three-way state, snapshots and safe sync |
| `backend/app/main.py` | Local HTTP API, OAuth, management, recovery, search and training |
| `frontend/src/App.tsx` | Study Manager, Explorer/Chapter Editor, Training and Settings |
| `scripts/` | Repeatable install, development startup and checks |

## Tests

```bash
bash scripts/check.sh
# Browser integration, with installed Chromium:
cd frontend
PCE_CHROMIUM_PATH=/usr/bin/chromium npm run test:e2e
# Alternatively: npx playwright install chromium, then npm run test:e2e
```

The browser suite starts its own server on port 8001 with a disposable temporary
SQLite database and mocked outbound Lichess traffic. It exercises the real built
frontend, FastAPI endpoints and chessboard. Run `npm run build` first if source
changed. It never uses a real account or seeds fixture studies in the normal app.

Tests cover multi-study/chapter imports, nested trees, comments/NAGs, custom FEN,
transpositions, occurrence counts, chapter-isolated edits, undo/redo, PGN round-trip,
no-change/local-only/remote-only/conflicting sync, remote deletion, backup/recovery,
upload failures, timeouts, authorization, post-write verification, partial updates,
stale previews, simultaneous pushes, rate limits, OAuth PKCE, disabled live writes,
training alternatives, frontend confirmation gates and mobile/desktop workflows.

## Validation and remaining work

Local execution, frontend builds, automated mocked API checks and browser
integration are verified. This cloud instance's network proxy currently denies
`lichess.org` (CONNECT HTTP 403); the environment configuration draft includes
the required domain addition. Review/save that change in environment settings and
publish the environment, then validate a configured public study and the OAuth
flow from your local browser. Live downloads, private-account OAuth and disposable
study writes have not been verified against Lichess in this instance.

Validation results: **41 backend tests, 8 frontend tests and 2 browser integration
tests passed**, along with the TypeScript/Vite production build. Backend test
output includes one upstream Starlette/httpx TestClient deprecation warning.

Not implemented: optional Stockfish evaluation/MultiPV, automatic sync,
automatic three-way merging, nested category management, FTS search for very large
libraries, cross-process locks, encrypted/keychain credential storage and full
Lichess lesson metadata preservation. These do not use placeholder API endpoints;
the Settings page explicitly identifies the unavailable engine feature.
