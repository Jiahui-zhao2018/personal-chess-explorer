# Repository guide

## Project and architecture

Personal Chess Explorer is a local, single-user repertoire explorer, chapter
editor, and trainer integrated with multiple explicitly configured Lichess Studies.
Studies are the canonical source of chess data; SQLite holds cached chapters,
pending edits, indexes, snapshots, backups, and training history. Do not introduce
game-history or external repertoire imports implicitly.

The frontend uses React, strict TypeScript, Vite, Tailwind CSS, react-chessboard,
and chess.js. The backend uses FastAPI, python-chess, SQLAlchemy, and SQLite.
Run one backend worker: sync locks, review tokens, and OAuth state are in memory.

## Main modules

- `frontend/src/App.tsx`: Explorer/Chapter Editor, Studies, Training, and Settings.
- `frontend/src/api.ts`, `types.ts`, `chess.ts`: typed `/api` requests, shared
  frontend models, and legal move helpers; `style.css` supplies styling.
- `backend/app/main.py`: HTTP routes, OAuth, management, search, and training.
- `backend/app/lichess.py`: official Lichess API client, credentials, authorization,
  and rate limiting.
- `backend/app/pgn.py`: PGN validation/export, tree editing, UCI paths, chapter
  identity, position keys, and semantic hashes.
- `backend/app/service.py`: indexing, snapshots, three-way state, and safe sync.
- `backend/app/db.py`, `migrations.py`: SQLAlchemy models and versioned SQLite schema.
- `backend/tests/`: pytest API/PGN/sync tests and mocked browser server.
- `frontend/src/*.test.*`, `frontend/e2e/`, `frontend/preview-e2e/`: unit, browser,
  and cloud preview tests. `scripts/tests/` tests process supervision.
- `scripts/`: dependency installation, concurrent dev servers, and combined checks.

## Coding and change conventions

- Match existing formatting: Python uses four spaces and snake_case; TypeScript
  uses two spaces, double quotes, semicolons, functional components, and hooks.
- Keep frontend models in `types.ts` and requests through `api.ts`; retain strict
  TypeScript checking. Follow existing Pydantic request models and SQLAlchemy
  session patterns in the backend.
- Use python-chess and chess.js for chess rules; extend the existing parser and
  tree model rather than implementing a replacement PGN parser.
- Prefer minimal, focused changes. Preserve existing functionality and data;
  add regression tests for behavioral fixes. Use migrations for schema changes.
- Keep credentials, private PGNs, `.env`, and runtime data out of Git and logs.
- Update `README.md` when installation steps, architecture, configuration, or APIs
  change. Document limitations honestly, especially unverified live API behavior.

## Setup and tests

Run from the repository root unless a command explicitly changes directory:

```bash
bash scripts/install.sh
bash scripts/dev.sh  # backend 127.0.0.1:8000; frontend 0.0.0.0:5173
bash scripts/check.sh  # all pytest tests, frontend unit tests, production build
.venv/bin/python -m pytest -q backend/tests
.venv/bin/python -m pytest -q scripts/tests
(cd frontend && npm test)
(cd frontend && npm run build)
(cd frontend && PCE_CHROMIUM_PATH=/usr/bin/chromium npm run test:e2e)
(cd frontend && PCE_CHROMIUM_PATH=/usr/bin/chromium npm run test:preview)
```

Browser tests require Chromium: use the installed executable above, or run
`npx playwright install chromium` in `frontend` and omit `PCE_CHROMIUM_PATH`.
Build before `test:e2e`; its fixture server uses port 8001. Preview tests also use
5174. Tests use temporary databases and mocked Lichess, not real account writes.
For cloud preview, select port 5173 and set `PCE_FRONTEND_ORIGIN` to the exact
preview origin when needed; preserve host/origin restrictions.

## Lichess synchronization and PGN integrity

- Never overwrite remote Study data without conflict detection and explicit
  authorization. Preserve baseline/local/remote comparison, single-use expiring
  review tokens, local hash checks, and an immediate remote re-fetch before writing.
  Conflicts or remote-only changes require additional explicit overwrite consent.
- Keep live writes disabled by default. Writes require `study:write`, account
  permissions, and the `PCE_WRITE_STUDY_IDS` allowlist. Verify live behavior only
  on an explicitly authorized disposable study before enabling important data.
- Commit remote backups before writes and verify the resulting PGN afterward.
  Preserve pending edits and the old baseline on uncertain/partial failures;
  never automatically retry writes. Moves and tags are separate non-atomic calls,
  and Lichess offers no atomic compare-and-swap.
- Preserve legal nested variations, SAN including correct `+`/`#`, comments,
  starting comments, NAGs, clock/evaluation directives, tags, and custom starting
  FEN. Canonical formatting is acceptable; losing supported content is not.
- Preserve study/chapter references using `ChapterURL` (legacy `Site` fallback);
  reject missing or ambiguous identities rather than guessing. Keep UCI node paths
  and chapter occurrences independent, including at transpositions.
- Support standard chess only; retain immutable identity/variant/orientation/FEN
  tag rules. Do not promise preservation of Lichess properties absent from PGN.
- Pulls must retain unsynchronized edits. Remote deletion blocks upload; backup
  restoration creates local pending edits, not an automatic remote overwrite.
