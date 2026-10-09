import { useEffect, useRef, useState } from "react";
import { Chess } from "chess.js";
import { Chessboard } from "react-chessboard";
import { api } from "./api";
import { legalMove, playUci, START } from "./chess";
import type {
  Answer,
  Chapter,
  Exercise,
  Explorer,
  Preview,
  Reference,
  Study,
} from "./types";

const pages = ["Explorer", "Studies", "Training", "Settings"] as const;
type Page = (typeof pages)[number];
const empty: Explorer = { position: "", occurrences: [], moves: [] };
const statusLabel: Record<string, string> = {
  synced: "Synced",
  pending: "Local changes pending",
  remote_changed: "Remote changes detected",
  conflict: "Conflict",
  uploading: "Uploading",
  error: "Error",
};
function Badge({ status }: { status: string }) {
  return (
    <span className={"badge " + status}>{statusLabel[status] || status}</span>
  );
}
function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not fetched yet";
}
function Source({
  reference,
  open,
}: {
  reference: Reference;
  open: (id: string, path?: string) => void;
}) {
  return (
    <div className="source">
      <div>
        <button
          className="text-button"
          onClick={() => open(reference.chapter_id, reference.path)}
        >
          {reference.chapter}
        </button>
        <small>
          {reference.study} {reference.category && " · " + reference.category}
        </small>
      </div>
      <a
        href={reference.url}
        target="_blank"
        rel="noreferrer"
        aria-label={"Open " + reference.chapter + " on Lichess"}
      >
        ↗
      </a>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("Explorer");
  const [studies, setStudies] = useState<Study[]>([]);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [auth, setAuth] = useState({
    authenticated: false,
    write: false,
    scopes: [] as string[],
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [study, setStudy] = useState("");
  const [category, setCategory] = useState("");
  const [side, setSide] = useState("");
  const [chapterFilter, setChapterFilter] = useState("");
  const [opening, setOpening] = useState("");
  const [history, setHistory] = useState([{ fen: START, san: "Start" }]);
  const [cursor, setCursor] = useState(0);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [nodeId, setNodeId] = useState("");
  const [mode, setMode] = useState<"explore" | "edit">("explore");
  const [explorer, setExplorer] = useState<Explorer>(empty);
  const [flipped, setFlipped] = useState(false);
  const [selectedSquare, setSelectedSquare] = useState("");
  const [promotion, setPromotion] = useState("q");
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Reference[] | null>(null);
  const [fenInput, setFenInput] = useState("");
  const [comment, setComment] = useState("");
  const [nags, setNags] = useState("");
  const [tagKey, setTagKey] = useState("Opening");
  const [tagValue, setTagValue] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [manualPgn, setManualPgn] = useState("");
  const [exercise, setExercise] = useState<Exercise | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [progress, setProgress] = useState({ attempts: 0, correct: 0 });
  const [backups, setBackups] = useState<
    { id: number; chapter_id: string; created: string }[]
  >([]);
  const [newStudy, setNewStudy] = useState({
    url: "",
    label: "",
    category: "",
    side: "both",
  });
  const [newChapter, setNewChapter] = useState({
    study: "",
    name: "",
    pgn: "",
  });
  const [importPreview, setImportPreview] = useState<{
    token: string;
    pgn: string;
    name: string;
    can_write: boolean;
  } | null>(null);
  const busyRef = useRef(false);
  const node = chapter?.nodes.find((n) => n.id === nodeId);
  const fen =
    page === "Training" && exercise && !exercise.done
      ? exercise.fen
      : mode === "edit" && node
        ? node.fen
        : history[cursor].fen;
  const filters = new URLSearchParams({
    study,
    category,
    side,
    chapter: chapterFilter,
    opening,
  }).toString();

  async function run(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function reload() {
    const [s, c, a, b, p] = await Promise.all([
      api<Study[]>("/studies"),
      api<Chapter[]>("/chapters"),
      api<typeof auth>("/auth/status"),
      api<typeof backups>("/backups"),
      api<typeof progress>("/training/progress"),
    ]);
    setStudies(s);
    setChapters(c);
    setAuth(a);
    setBackups(b);
    setProgress(p);
    setRevision((r) => r + 1);
  }
  useEffect(() => {
    void run(reload);
  }, []);
  useEffect(() => {
    let live = true;
    if (page !== "Explorer") return;
    api<Explorer>("/explorer?" + filters + "&fen=" + encodeURIComponent(fen))
      .then((data) => {
        if (live) setExplorer(data);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [fen, filters, revision, page]);
  useEffect(() => {
    setComment(node?.comment || "");
    setNags(node?.nags.join(", ") || "");
    setSelectedSquare("");
  }, [node?.id, chapter?.hash]);
  async function loadChapter(id: string, path = "") {
    const c = await api<Chapter>("/chapters/" + id);
    setChapter(c);
    setNodeId(c.nodes.some((n) => n.id === path) ? path : "");
    setManualPgn(c.pgn);
    setMode("edit");
    setPage("Explorer");
    setPreview(null);
  }
  function openChapter(id: string, path = "") {
    void run(() => loadChapter(id, path));
  }
  function navigate(direction: number) {
    if (mode === "edit" && chapter && node) {
      if (direction < 0) setNodeId(node.parent);
      else if (node.children[0]) setNodeId(node.children[0]);
    } else
      setCursor((c) =>
        Math.max(0, Math.min(history.length - 1, c + direction)),
      );
  }
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        page !== "Explorer" ||
        preview ||
        busy ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(
          (e.target as HTMLElement).tagName,
        )
      )
        return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        navigate(e.key === "ArrowLeft" ? -1 : 1);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [page, preview, busy, mode, chapter, nodeId, history]);
  async function edit(action: string, extra: Record<string, unknown> = {}) {
    if (!chapter) throw new Error("Select one chapter before editing");
    const c = await api<Chapter>("/chapters/" + chapter.id + "/edit", {
      action,
      path: nodeId,
      expected_hash: chapter.hash,
      ...extra,
    });
    setChapter(c);
    if (!c.nodes.some((n) => n.id === nodeId)) setNodeId(node?.parent || "");
    setPreview(null);
    setRevision((r) => r + 1);
    return c;
  }
  function move(from: string, to: string, promote = promotion) {
    if (busy || (page === "Training" && (!exercise || exercise.done || answer)))
      return false;
    const result = legalMove(fen, from, to, promote);
    if (!result) return false;
    setSelectedSquare("");
    if (page === "Training")
      void run(async () => {
        const a = await api<Answer>("/training/answer", {
          token: exercise!.token,
          uci: result.uci,
        });
        setAnswer(a);
        await reload();
      });
    else if (mode === "edit")
      void run(async () => {
        await edit("add", { uci: result.uci });
        setNodeId((nodeId + "/" + result.uci).replace(/^\//, ""));
      });
    else {
      setHistory([
        ...history.slice(0, cursor + 1),
        { fen: result.fen, san: result.san },
      ]);
      setCursor(cursor + 1);
    }
    return true;
  }
  function chooseUci(uci: string) {
    move(uci.slice(0, 2), uci.slice(2, 4), uci[4] || promotion);
  }
  function clickSquare(square: string) {
    if (selectedSquare && move(selectedSquare, square)) return;
    setSelectedSquare(square);
  }
  function jumpFen(value: string) {
    try {
      const board = new Chess(value);
      setHistory([{ fen: board.fen(), san: "FEN position" }]);
      setCursor(0);
      setMode("explore");
      setError("");
    } catch {
      setError("Enter a valid standard-chess FEN");
    }
  }
  async function nextExercise() {
    setAnswer(null);
    setExercise(await api<Exercise>("/training/next?" + filters));
    setSelectedSquare("");
  }
  async function refresh(sid?: string) {
    const result = await api<
      { ok: boolean; error?: string }[] | { refreshed: string }
    >(sid ? "/studies/" + sid + "/refresh" : "/refresh", {});
    await reload();
    if (chapter) {
      const c = await api<Chapter>("/chapters/" + chapter.id);
      setChapter(c);
    }
    if (Array.isArray(result) && result.some((r) => !r.ok))
      throw new Error(
        result
          .filter((r) => !r.ok)
          .map((r) => r.error)
          .join("; "),
      );
  }
  const categories = [
    ...new Set(studies.map((s) => s.category).filter(Boolean)),
  ];
  const board = (
    <div className="board-wrap">
      <Chessboard
        options={{
          id: "repertoire-board",
          position: fen,
          boardOrientation: flipped ? "black" : "white",
          darkSquareStyle: { backgroundColor: "#6b8976" },
          lightSquareStyle: { backgroundColor: "#e8e8d7" },
          squareStyles: selectedSquare
            ? { [selectedSquare]: { backgroundColor: "#d7b865" } }
            : {},
          onPieceDrop: ({ sourceSquare, targetSquare }) =>
            targetSquare ? move(sourceSquare, targetSquare) : false,
          onSquareClick: ({ square }) => clickSquare(square),
          allowDragging: !busy && !(page === "Training" && !!answer),
        }}
      />
    </div>
  );
  const filterBar = (
    <div className="filters">
      <select
        aria-label="Study filter"
        value={study}
        onChange={(e) => setStudy(e.target.value)}
      >
        <option value="">All enabled studies</option>
        {studies.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label || s.title || s.id}
          </option>
        ))}
      </select>
      <select
        aria-label="Category filter"
        value={category}
        onChange={(e) => setCategory(e.target.value)}
      >
        <option value="">All categories</option>
        {categories.map((c) => (
          <option key={c}>{c}</option>
        ))}
      </select>
      <select
        aria-label="Repertoire side"
        value={side}
        onChange={(e) => setSide(e.target.value)}
      >
        <option value="">Both colors</option>
        <option value="white">White</option>
        <option value="black">Black</option>
      </select>
      <select
        aria-label="Chapter filter"
        value={chapterFilter}
        onChange={(e) => setChapterFilter(e.target.value)}
      >
        <option value="">All chapters</option>
        {chapters
          .filter((c) => !study || c.study_id === study)
          .map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
      </select>
    </div>
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">♘</span>
          <div>
            Personal Chess<small>EXPLORER</small>
          </div>
        </div>
        <div className="nav-label">YOUR REPERTOIRE</div>
        <nav>
          {pages.map((p, i) => (
            <button
              key={p}
              className={page === p ? "active" : ""}
              onClick={() => setPage(p)}
            >
              <span>{["◈", "▤", "◎", "⚙"][i]}</span>
              {p}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="connection-dot" /> Local workspace
          <small>Lichess Studies are the source.</small>
          <small>
            {auth.authenticated
              ? auth.write
                ? "Connected · read & write"
                : "Connected · read only"
              : "Public studies · read only"}
          </small>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <div className="eyebrow">PERSONAL CHESS EXPLORER</div>
            <h1>
              {page === "Explorer"
                ? "Your repertoire, connected."
                : page === "Studies"
                  ? "A library of your own."
                  : page === "Training"
                    ? "Make the next move."
                    : "Your local workspace."}
            </h1>
            <p>
              {page === "Explorer"
                ? "Explore every line. Keep every source."
                : page === "Studies"
                  ? "Only the Lichess Studies you choose belong here."
                  : page === "Training"
                    ? "Practice the continuations in your selected chapters."
                    : "Manage authentication, recovery, and local data."}
            </p>
          </div>
          <button
            className="primary"
            disabled={busy || !studies.length}
            onClick={() => void run(() => refresh())}
          >
            {busy ? "Working…" : "↻ Sync from Lichess"}
          </button>
        </header>
        {error && (
          <div role="alert" className="error-banner">
            {error}
            <button onClick={() => setError("")} aria-label="Dismiss error">
              ×
            </button>
          </div>
        )}
        {page === "Explorer" && (
          <>
            <div className="workspace-toolbar">
              <div className="segmented">
                <button
                  className={mode === "explore" ? "chosen" : ""}
                  onClick={() => setMode("explore")}
                >
                  Explore
                </button>
                <button
                  className={mode === "edit" ? "chosen" : ""}
                  disabled={!chapter}
                  onClick={() => setMode("edit")}
                >
                  Edit chapter
                </button>
              </div>
              <span className="muted">
                {mode === "edit"
                  ? chapter?.name
                  : "Position-based · transpositions included"}
              </span>
              {chapter && mode === "edit" && <Badge status={chapter.status} />}
            </div>
            {filterBar}
            <div className="explorer-grid">
              <section className="board-column">
                {board}
                <div className="board-controls">
                  <button
                    onClick={() => {
                      if (mode === "edit") setNodeId("");
                      else setCursor(0);
                    }}
                    aria-label="Go to start"
                  >
                    |←
                  </button>
                  <button
                    onClick={() => navigate(-1)}
                    aria-label="Previous move"
                  >
                    ←
                  </button>
                  <button onClick={() => navigate(1)} aria-label="Next move">
                    →
                  </button>
                  <span />
                  <button onClick={() => setFlipped((f) => !f)}>⇅ Flip</button>
                  <select
                    aria-label="Promotion piece"
                    value={promotion}
                    onChange={(e) => setPromotion(e.target.value)}
                  >
                    <option value="q">Promote: Queen</option>
                    <option value="r">Rook</option>
                    <option value="b">Bishop</option>
                    <option value="n">Knight</option>
                  </select>
                </div>
                <div className="card move-trail">
                  <div className="section-label">
                    {mode === "edit"
                      ? "CHAPTER VARIATIONS"
                      : "YOUR EXPLORATION"}
                  </div>
                  {mode === "edit" && chapter ? (
                    <div className="tree">
                      {chapter.nodes.map((n) => (
                        <div
                          key={n.id}
                          style={{ paddingLeft: Math.min(n.depth, 12) * 12 }}
                        >
                          <button
                            className={n.id === nodeId ? "selected-node" : ""}
                            onClick={() => setNodeId(n.id)}
                          >
                            {n.label || n.san}
                            {n.nags.length > 0 ? " $" + n.nags.join(" $") : ""}
                            {n.comment ? " ◌" : ""}
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="trail">
                      {history.map((h, i) => (
                        <button
                          key={i}
                          className={cursor === i ? "selected-node" : ""}
                          onClick={() => setCursor(i)}
                        >
                          {i ? `${Math.ceil(i / 2)}${i % 2 ? "." : "…"} ` : ""}
                          {h.san}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <details className="fen">
                  <summary>Position FEN</summary>
                  <code>{fen}</code>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      jumpFen(fenInput);
                    }}
                  >
                    <input
                      aria-label="Jump to FEN"
                      placeholder="Paste a FEN position"
                      value={fenInput}
                      onChange={(e) => setFenInput(e.target.value)}
                    />
                    <button>Go</button>
                  </form>
                </details>
              </section>
              <section className="analysis-column">
                <div className="card">
                  <div className="card-heading">
                    <div>
                      <div className="section-label">
                        RECORDED CONTINUATIONS
                      </div>
                      <h2>
                        {mode === "edit"
                          ? "This chapter’s lines"
                          : "The next move"}
                      </h2>
                    </div>
                    <span className="count">
                      {mode === "edit"
                        ? node?.children.length || 0
                        : explorer.moves.length}
                    </span>
                  </div>
                  {mode === "explore" ? (
                    <>
                      <table>
                        <thead>
                          <tr>
                            <th>Move</th>
                            <th>Studies</th>
                            <th>Chapters</th>
                            <th>Occurrences</th>
                          </tr>
                        </thead>
                        <tbody>
                          {explorer.moves.map((m) => (
                            <tr key={m.uci}>
                              <td>
                                <button
                                  className="move-button"
                                  disabled={busy}
                                  onClick={() => chooseUci(m.uci)}
                                >
                                  {m.san} <span>→</span>
                                </button>
                              </td>
                              <td>{m.studies}</td>
                              <td>{m.chapters}</td>
                              <td>{m.occurrences}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!explorer.moves.length && (
                        <div className="empty-state">
                          <span>♘</span>
                          <h3>
                            {studies.length
                              ? "No recorded continuation here"
                              : "Build your repertoire library"}
                          </h3>
                          <p>
                            {studies.length
                              ? "Move back, explore another line, or import a study containing this position."
                              : "Add a Lichess Study, then sync its chapters to begin exploring."}
                          </p>
                          {!studies.length && (
                            <button
                              className="primary"
                              onClick={() => setPage("Studies")}
                            >
                              Add your first study
                            </button>
                          )}
                        </div>
                      )}
                      <div className="table-note">
                        Counts describe occurrences in studies, not played
                        games.
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="chapter-continuations">
                        {node?.children.map((id) => {
                          const n = chapter?.nodes.find((n) => n.id === id);
                          return (
                            <button key={id} onClick={() => setNodeId(id)}>
                              {n?.san} →
                            </button>
                          );
                        })}
                        {!node?.children.length && (
                          <p className="muted">
                            End of this variation. Make a legal move to extend
                            it.
                          </p>
                        )}
                      </div>
                      <p className="table-note">
                        Board moves edit only <strong>{chapter?.name}</strong>.
                        Other chapters remain independent.
                      </p>
                    </>
                  )}
                </div>
                {mode === "edit" && chapter ? (
                  <div className="card editor">
                    <div className="card-heading">
                      <h2>Chapter workspace</h2>
                      <a
                        href={"https://lichess.org/study/" + chapter.id}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Lichess ↗
                      </a>
                    </div>
                    <div className="button-row">
                      <button
                        disabled={busy || !chapter.can_undo}
                        onClick={() =>
                          void run(async () => {
                            await edit("undo");
                          })
                        }
                      >
                        Undo
                      </button>
                      <button
                        disabled={busy || !chapter.can_redo}
                        onClick={() =>
                          void run(async () => {
                            await edit("redo");
                          })
                        }
                      >
                        Redo
                      </button>
                      <button
                        disabled={busy || !nodeId}
                        onClick={() =>
                          void run(async () => {
                            await edit("promote");
                          })
                        }
                      >
                        Make mainline
                      </button>
                      <button
                        disabled={busy || !nodeId}
                        className="danger"
                        onClick={() => {
                          if (
                            window.confirm(
                              "Delete this variation and all its descendants locally?",
                            )
                          )
                            void run(async () => {
                              await edit("delete");
                            });
                        }}
                      >
                        Delete variation
                      </button>
                      <button
                        disabled={busy || (node?.children.length || 0) < 2}
                        onClick={() =>
                          void run(async () => {
                            await edit("reorder", {
                              order: node!.children
                                .map(
                                  (id) =>
                                    chapter.nodes.find((n) => n.id === id)!.uci,
                                )
                                .reverse(),
                            });
                          })
                        }
                      >
                        Reverse child order
                      </button>
                    </div>
                    <label>
                      Position comment
                      <textarea
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        rows={4}
                      />
                    </label>
                    <label>
                      NAG annotations
                      <input
                        value={nags}
                        onChange={(e) => setNags(e.target.value)}
                        placeholder="1, 14 (numeric glyphs)"
                      />
                    </label>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await edit("annotate", {
                            comment,
                            nags: nags.trim()
                              ? nags.split(",").map((n) => Number(n.trim()))
                              : [],
                          });
                        })
                      }
                    >
                      Save annotations locally
                    </button>
                    <details>
                      <summary>PGN tags</summary>
                      <dl className="tags">
                        {Object.entries(chapter.tags).map(([k, v]) => (
                          <div key={k}>
                            <dt>{k}</dt>
                            <dd>{v}</dd>
                          </div>
                        ))}
                      </dl>
                      <div className="button-row">
                        <input
                          aria-label="Tag name"
                          value={tagKey}
                          onChange={(e) => setTagKey(e.target.value)}
                        />
                        <input
                          aria-label="Tag value"
                          value={tagValue}
                          onChange={(e) => setTagValue(e.target.value)}
                          placeholder="Empty value removes the tag"
                        />
                        <button
                          disabled={busy}
                          onClick={() =>
                            void run(async () => {
                              await edit("tags", {
                                tags: { [tagKey]: tagValue },
                              });
                            })
                          }
                        >
                          Save tag
                        </button>
                      </div>
                    </details>
                    <div className="sync-footer">
                      <span>Edits stay local until verified on Lichess.</span>
                      <button
                        className="primary"
                        disabled={busy || chapter.deleted}
                        onClick={() =>
                          void run(async () => {
                            const p = await api<Preview>(
                              "/chapters/" + chapter.id + "/preview",
                              {},
                            );
                            setPreview(p);
                            setConfirmed(false);
                            setOverwrite(false);
                            setManualPgn(p.local);
                          })
                        }
                      >
                        Review synchronization
                      </button>
                    </div>
                    {chapter.error && (
                      <p className="inline-error">{chapter.error}</p>
                    )}
                  </div>
                ) : (
                  <div className="card">
                    <div className="card-heading">
                      <div>
                        <div className="section-label">SOURCE CHAPTERS</div>
                        <h2>Where this position lives</h2>
                      </div>
                      <span className="count">
                        {explorer.occurrences.length}
                      </span>
                    </div>
                    {explorer.occurrences.map((r, i) => (
                      <div
                        className="occurrence"
                        key={r.chapter_id + r.path + i}
                      >
                        <Source reference={r} open={openChapter} />
                        <Badge status={r.status} />
                        {r.comment && <p className="comment">{r.comment}</p>}
                        {r.nags.length > 0 && (
                          <small>NAGs: {r.nags.join(", ")}</small>
                        )}
                        <small className="path">
                          {r.path || "Starting position"}
                        </small>
                      </div>
                    ))}
                    {!explorer.occurrences.length && (
                      <p className="muted padded">
                        No imported chapter contains this position.
                      </p>
                    )}
                    {explorer.moves.length > 0 && (
                      <details className="padded">
                        <summary>Continuation notes & sources</summary>
                        {explorer.moves.map((m) => (
                          <div key={m.uci}>
                            <h3>{m.san}</h3>
                            {m.references.map((r, i) => (
                              <div key={r.chapter_id + r.path + i}>
                                <Source reference={r} open={openChapter} />
                                {r.comment && (
                                  <p className="comment">{r.comment}</p>
                                )}
                                {r.nags.length > 0 && (
                                  <small>NAGs: {r.nags.join(", ")}</small>
                                )}
                              </div>
                            ))}
                          </div>
                        ))}
                      </details>
                    )}
                  </div>
                )}
                <div className="card search-card">
                  <h2>Find a position or idea</h2>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void run(async () =>
                        setSearchResults(
                          await api<Reference[]>(
                            "/search?" +
                              filters +
                              "&q=" +
                              encodeURIComponent(query),
                          ),
                        ),
                      );
                    }}
                  >
                    <input
                      aria-label="Search repertoire"
                      placeholder="Comment, opening, move, FEN…"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                    <button disabled={busy}>Search</button>
                  </form>
                  <input
                    aria-label="Opening filter"
                    value={opening}
                    onChange={(e) => setOpening(e.target.value)}
                    placeholder="Filter by Opening tag"
                  />
                  {searchResults?.map((r, i) => (
                    <div key={r.chapter_id + r.path + i}>
                      <Source reference={r} open={openChapter} />
                      <button
                        className="text-button"
                        onClick={() => jumpFen(r.fen)}
                      >
                        Explore this position
                      </button>
                      <p className="comment">{r.comment}</p>
                    </div>
                  ))}
                  {searchResults?.length === 0 && (
                    <p className="muted">No matching occurrence.</p>
                  )}
                </div>
              </section>
            </div>
          </>
        )}
        {page === "Studies" && (
          <>
            <div className="library-summary">
              <div>
                <strong>{studies.length}</strong>
                <span>configured studies</span>
              </div>
              <div>
                <strong>{chapters.length}</strong>
                <span>cached chapters</span>
              </div>
              <div>
                <strong>
                  {chapters.filter((c) => c.status !== "synced").length}
                </strong>
                <span>chapters to review</span>
              </div>
            </div>
            <section className="card add-study">
              <h2>Add a Lichess Study</h2>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(async () => {
                    const s = await api<{ id: string }>("/studies", newStudy);
                    setNewStudy({
                      url: "",
                      label: "",
                      category: "",
                      side: "both",
                    });
                    await reload();
                    await refresh(s.id);
                  });
                }}
              >
                <label>
                  Study URL or ID
                  <input
                    required
                    value={newStudy.url}
                    onChange={(e) =>
                      setNewStudy({ ...newStudy, url: e.target.value })
                    }
                    placeholder="https://lichess.org/study/abcdefgh"
                  />
                </label>
                <label>
                  Custom label
                  <input
                    value={newStudy.label}
                    onChange={(e) =>
                      setNewStudy({ ...newStudy, label: e.target.value })
                    }
                    placeholder="My Ruy Lopez"
                  />
                </label>
                <label>
                  Category
                  <input
                    value={newStudy.category}
                    onChange={(e) =>
                      setNewStudy({ ...newStudy, category: e.target.value })
                    }
                    placeholder="White repertoire"
                  />
                </label>
                <label>
                  Repertoire color
                  <select
                    value={newStudy.side}
                    onChange={(e) =>
                      setNewStudy({ ...newStudy, side: e.target.value })
                    }
                  >
                    <option value="both">Both</option>
                    <option value="white">White</option>
                    <option value="black">Black</option>
                  </select>
                </label>
                <button className="primary" disabled={busy}>
                  Add & fetch
                </button>
              </form>
            </section>
            <div className="study-list">
              {studies.map((s) => (
                <section className="card study-card" key={s.id}>
                  <div className="card-heading">
                    <div>
                      <div className="section-label">
                        {s.category || "UNCATEGORIZED"}
                      </div>
                      <h2>{s.label || s.title || s.id}</h2>
                      <small>
                        {s.title || s.id} · Last successful pull:{" "}
                        {date(s.fetched)}
                      </small>
                    </div>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={s.enabled}
                        disabled={busy}
                        onChange={(e) =>
                          void run(async () => {
                            await api(
                              "/studies/" + s.id,
                              { enabled: e.target.checked },
                              "PATCH",
                            );
                            await reload();
                          })
                        }
                      />
                      Enabled
                    </label>
                  </div>
                  <div className="button-row">
                    <a
                      href={"https://lichess.org/study/" + s.id}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open on Lichess ↗
                    </a>
                    <button
                      disabled={busy}
                      onClick={() => void run(() => refresh(s.id))}
                    >
                      Refresh
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => {
                        const label = window.prompt("Custom label", s.label);
                        if (label !== null)
                          void run(async () => {
                            await api("/studies/" + s.id, { label }, "PATCH");
                            await reload();
                          });
                      }}
                    >
                      Rename label
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => {
                        const category = window.prompt("Category", s.category);
                        if (category !== null)
                          void run(async () => {
                            await api(
                              "/studies/" + s.id,
                              { category },
                              "PATCH",
                            );
                            await reload();
                          });
                      }}
                    >
                      Change category
                    </button>
                    <select
                      aria-label={"Color for " + s.id}
                      value={s.side}
                      disabled={busy}
                      onChange={(e) =>
                        void run(async () => {
                          await api(
                            "/studies/" + s.id,
                            { side: e.target.value },
                            "PATCH",
                          );
                          await reload();
                        })
                      }
                    >
                      <option value="both">Both colors</option>
                      <option value="white">White</option>
                      <option value="black">Black</option>
                    </select>
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Remove this study locally, including pending edits, training history and backups? The Lichess study will remain.",
                          )
                        )
                          void run(async () => {
                            await api(
                              "/studies/" + s.id,
                              { confirmed: true },
                              "DELETE",
                            );
                            if (chapter?.study_id === s.id) {
                              setChapter(null);
                              setMode("explore");
                            }
                            await reload();
                          });
                      }}
                    >
                      Remove locally
                    </button>
                  </div>
                  {s.error && <p className="inline-error">{s.error}</p>}
                  <div className="chapter-list">
                    {chapters
                      .filter((c) => c.study_id === s.id)
                      .map((c) => (
                        <div key={c.id}>
                          <button
                            className="text-button"
                            onClick={() => openChapter(c.id)}
                          >
                            {c.name}
                            {c.deleted ? " (removed remotely)" : ""}
                          </button>
                          <Badge status={c.status} />
                        </div>
                      ))}
                  </div>
                </section>
              ))}
            </div>
            {!studies.length && (
              <p className="muted">
                Your library is empty. Public studies work without signing in.
              </p>
            )}
          </>
        )}
        {page === "Training" && (
          <>
            {filterBar}
            <div className="training-grid">
              <div>
                {exercise && !exercise.done ? (
                  board
                ) : (
                  <div className="card training-start">
                    <span>◎</span>
                    <h2>
                      {exercise?.done
                        ? "All selected reviews are complete"
                        : "Learn your own lines"}
                    </h2>
                    <p>
                      {exercise?.done
                        ? "Try another filter, or return when the next review is due."
                        : "Prepared continuations are hidden until you answer. Every valid alternative in the selected chapter counts."}
                    </p>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() => void run(nextExercise)}
                    >
                      Start review
                    </button>
                  </div>
                )}
                <div className="board-controls">
                  <button onClick={() => setFlipped((f) => !f)}>⇅ Flip</button>
                  <select
                    aria-label="Training promotion"
                    value={promotion}
                    onChange={(e) => setPromotion(e.target.value)}
                  >
                    {["q", "r", "b", "n"].map((p) => (
                      <option key={p}>{p}</option>
                    ))}
                  </select>
                </div>
              </div>
              <section className="card training-panel">
                <div className="section-label">REPERTOIRE PRACTICE</div>
                <h2>
                  {exercise && !exercise.done
                    ? exercise.chapter
                    : "Your progress"}
                </h2>
                <p className="muted">{exercise?.study}</p>
                {exercise && !exercise.done && !answer && (
                  <p>
                    Find a prepared continuation. Drag a piece or click its
                    starting and destination squares.
                  </p>
                )}
                {answer && (
                  <div
                    className={
                      answer.correct ? "answer correct" : "answer incorrect"
                    }
                  >
                    <h3>
                      {answer.correct
                        ? "That’s in your repertoire."
                        : "A different line is prepared here."}
                    </h3>
                    <p>
                      Valid continuations:{" "}
                      {answer.moves.map((m) => m.san).join(", ")}
                    </p>
                    <p>{answer.comment}</p>
                    {answer.moves.map((m) => (
                      <p key={m.uci}>
                        <strong>{m.san}</strong> {m.comment}{" "}
                        {m.nags.map((n) => "$" + n).join(" ")}
                      </p>
                    ))}
                    <small>Next review: {date(answer.due)}</small>
                  </div>
                )}
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => void run(nextExercise)}
                >
                  {answer ? "Next exercise" : "Choose an exercise"}
                </button>
                <div className="progress-stats">
                  <div>
                    <strong>{progress.attempts}</strong>attempts
                  </div>
                  <div>
                    <strong>{progress.correct}</strong>correct
                  </div>
                </div>
                <small>Training history stays in this local workspace.</small>
              </section>
            </div>
          </>
        )}
        {page === "Settings" && (
          <div className="settings-grid">
            <section className="card padded">
              <div className="section-label">LICHESS CONNECTION</div>
              <h2>
                {auth.authenticated
                  ? "Account connected"
                  : "Connect your account"}
              </h2>
              <p>
                Public studies need no authentication. Connect with read
                permission for private studies; enable write permission only
                when you want to synchronize edits.
              </p>
              <div className="button-row">
                <a className="button" href="/api/auth/connect">
                  Connect read only
                </a>
                <a
                  className="button primary"
                  href="/api/auth/connect?write=true"
                >
                  Connect read & write
                </a>
                {auth.authenticated && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await api("/auth/disconnect", {});
                        await reload();
                      })
                    }
                  >
                    Disconnect locally
                  </button>
                )}
              </div>
              <p className="muted">
                Granted scopes: {auth.scopes.join(", ") || "None"}. OAuth tokens
                stay on the backend in an owner-only credential file.
              </p>
            </section>
            <section className="card padded">
              <div className="section-label">RECOVERY</div>
              <h2>Chapter backups</h2>
              <p>
                Remote PGN is backed up before an upload. Restoring a backup
                creates local pending edits; it never writes to Lichess.
              </p>
              {backups.map((b) => (
                <div className="backup" key={b.id}>
                  <div>
                    <strong>{b.chapter_id}</strong>
                    <small>{date(b.created)}</small>
                  </div>
                  <a
                    href={"/api/backups/" + b.id}
                    download={"backup-" + b.id + ".pgn"}
                  >
                    Download PGN
                  </a>
                  <button
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          "Restore this backup as local pending edits?",
                        )
                      )
                        void run(async () => {
                          const c = await api<Chapter>(
                            "/chapters/" + b.chapter_id,
                          );
                          await api("/backups/" + b.id + "/restore", {
                            confirmed: true,
                            expected_hash: c.hash,
                          });
                          await loadChapter(b.chapter_id);
                          await reload();
                        });
                    }}
                  >
                    Restore locally
                  </button>
                </div>
              ))}
              {!backups.length && (
                <p className="muted">No upload backups yet.</p>
              )}
            </section>
            <section className="card padded">
              <div className="section-label">NEW LICHESS CHAPTER</div>
              <h2>Add a chapter from PGN</h2>
              <p>
                This creates one new chapter in an explicitly configured study.
                Review it before any remote write.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(async () =>
                    setImportPreview(
                      await api(
                        "/studies/" + newChapter.study + "/new-chapter/preview",
                        { name: newChapter.name, pgn: newChapter.pgn },
                      ),
                    ),
                  );
                }}
              >
                <select
                  required
                  aria-label="New chapter study"
                  value={newChapter.study}
                  onChange={(e) => {
                    setNewChapter({ ...newChapter, study: e.target.value });
                    setImportPreview(null);
                  }}
                >
                  <option value="">Choose a study</option>
                  {studies.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label || s.title || s.id}
                    </option>
                  ))}
                </select>
                <input
                  required
                  placeholder="Chapter name"
                  aria-label="New chapter name"
                  value={newChapter.name}
                  onChange={(e) => {
                    setNewChapter({ ...newChapter, name: e.target.value });
                    setImportPreview(null);
                  }}
                />
                <textarea
                  required
                  rows={7}
                  aria-label="New chapter PGN"
                  value={newChapter.pgn}
                  onChange={(e) => {
                    setNewChapter({ ...newChapter, pgn: e.target.value });
                    setImportPreview(null);
                  }}
                  placeholder="Paste one chapter’s PGN"
                />
                <button disabled={busy}>Validate & preview</button>
              </form>
              {importPreview && (
                <div>
                  <h3>{importPreview.name}</h3>
                  <pre>{importPreview.pgn}</pre>
                  <button
                    className="primary"
                    disabled={busy || !importPreview.can_write}
                    onClick={() => {
                      if (window.confirm("Create this new chapter on Lichess?"))
                        void run(async () => {
                          const result = await api<{ created: string }>(
                            "/studies/" +
                              newChapter.study +
                              "/new-chapter/push",
                            { token: importPreview.token, confirmed: true },
                          );
                          setImportPreview(null);
                          await reload();
                          await loadChapter(result.created);
                        });
                    }}
                  >
                    Confirm creation on Lichess
                  </button>
                </div>
              )}
            </section>
            <section className="card padded">
              <div className="section-label">SYNCHRONIZATION & ANALYSIS</div>
              <h2>Manual, chapter by chapter</h2>
              <p>
                Remote changes never overwrite pending edits automatically.
                Review a chapter’s differences, keep the remote version, resolve
                the PGN manually, or explicitly authorize an overwrite.
              </p>
              <p>
                Move and tag updates are separate requests. A race remains
                between the final remote check and upload because Lichess offers
                no atomic version check.
              </p>
              <p className="muted">
                Stockfish analysis is not enabled in this version. No engine
                recommendations are added to your repertoire.
              </p>
            </section>
          </div>
        )}
        <footer>
          Personal Chess Explorer{" "}
          <span>
            Local cache · Canonical Lichess Studies · No game statistics
          </span>
        </footer>
      </main>
      {preview && chapter && (
        <div className="modal-backdrop">
          <section
            className="sync-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="sync-title"
          >
            <div className="card-heading">
              <div>
                <div className="section-label">SYNCHRONIZATION REVIEW</div>
                <h2 id="sync-title">{chapter.name}</h2>
              </div>
              <button
                disabled={busy}
                aria-label="Close sync preview"
                onClick={() => setPreview(null)}
              >
                ×
              </button>
            </div>
            <Badge status={preview.status} />
            <p>{preview.warning}</p>
            <div className="diff-grid">
              <div>
                <h3>Local changes from baseline</h3>
                <pre>{preview.local_diff || "No local changes"}</pre>
              </div>
              <div>
                <h3>Remote changes from baseline</h3>
                <pre>{preview.remote_diff || "No remote changes"}</pre>
              </div>
            </div>
            <details>
              <summary>Exact proposed upload difference</summary>
              <pre>{preview.upload_diff || "No difference"}</pre>
            </details>
            <details>
              <summary>Resolve manually with chapter PGN</summary>
              <textarea
                aria-label="Manual resolution PGN"
                value={manualPgn}
                onChange={(e) => setManualPgn(e.target.value)}
                rows={10}
              />
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const c = await api<Chapter>(
                      "/chapters/" + chapter.id + "/resolve",
                      {
                        choice: "manual",
                        pgn: manualPgn,
                        confirmed: true,
                        expected_hash: chapter.hash,
                      },
                    );
                    setChapter(c);
                    setPreview(null);
                    await reload();
                  })
                }
              >
                Save manual resolution locally
              </button>
            </details>
            <label className="check">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              I reviewed the full chapter replacement and authorize this upload.
            </label>
            {["conflict", "remote_changed"].includes(preview.status) && (
              <label className="check danger">
                <input
                  type="checkbox"
                  checked={overwrite}
                  onChange={(e) => setOverwrite(e.target.checked)}
                />
                Keep local: explicitly overwrite the remote changes shown above.
              </label>
            )}
            <div className="button-row">
              <button disabled={busy} onClick={() => setPreview(null)}>
                Cancel
              </button>
              <button
                disabled={busy}
                onClick={() => {
                  if (
                    window.confirm(
                      "Replace local edits with the latest remote chapter? A local backup will be saved.",
                    )
                  )
                    void run(async () => {
                      setChapter(
                        await api<Chapter>(
                          "/chapters/" + chapter.id + "/resolve",
                          {
                            choice: "remote",
                            confirmed: true,
                            expected_hash: chapter.hash,
                          },
                        ),
                      );
                      setPreview(null);
                      await reload();
                    });
                }}
              >
                Keep remote
              </button>
              <button
                className="primary"
                disabled={
                  busy ||
                  !confirmed ||
                  !preview.can_write ||
                  (["conflict", "remote_changed"].includes(preview.status) &&
                    !overwrite)
                }
                onClick={() =>
                  void run(async () => {
                    await api("/chapters/" + chapter.id + "/push", {
                      token: preview.token,
                      confirmed,
                      overwrite,
                    });
                    setPreview(null);
                    await loadChapter(chapter.id, nodeId);
                    await reload();
                  })
                }
              >
                Confirm push to Lichess
              </button>
            </div>
            {!preview.can_write && (
              <p className="muted">
                Uploading requires study:write permission and an explicitly
                enabled study ID in PCE_WRITE_STUDY_IDS. Start with an
                authorized disposable study; see the README for live
                verification.
              </p>
            )}
            {error && (
              <p role="alert" className="inline-error">
                {error}
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
