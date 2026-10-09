import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import App from "./App";
import { START, playUci } from "./chess";
import { api } from "./api";

vi.mock("./api", () => ({ api: vi.fn() }));
vi.mock("react-chessboard", () => ({
  Chessboard: ({
    options,
  }: {
    options: { onSquareClick: (p: { square: string }) => void };
  }) => (
    <div aria-label="Chessboard">
      <button onClick={() => options.onSquareClick({ square: "e2" })}>
        Square e2
      </button>
      <button onClick={() => options.onSquareClick({ square: "e4" })}>
        Square e4
      </button>
      <button onClick={() => options.onSquareClick({ square: "e5" })}>
        Square e5
      </button>
    </div>
  ),
}));
const source = {
  study_id: "study001",
  study: "My repertoire",
  chapter_id: "study001/chapter1",
  chapter: "Berlin",
  path: "",
  fen: START,
  comment: "Root idea",
  nags: [],
  status: "synced",
  url: "https://lichess.org/study/study001/chapter1",
  category: "White",
};
const chapter = {
  id: "study001/chapter1",
  study_id: "study001",
  remote_id: "chapter1",
  name: "Berlin",
  status: "pending",
  hash: "version1",
  pgn: "1. e4 *",
  tags: { Opening: "Ruy Lopez" },
  can_undo: true,
  can_redo: false,
  nodes: [
    {
      id: "",
      parent: "",
      fen: START,
      san: "Start",
      depth: 0,
      comment: "Root idea",
      nags: [],
      children: ["e2e4"],
    },
    {
      id: "e2e4",
      parent: "",
      fen: playUci(START, "e2e4")!.fen,
      san: "e4",
      depth: 1,
      comment: "Move idea",
      nags: [1],
      children: [],
    },
  ],
};
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, body) => {
    if (path === "/studies")
      return [
        {
          id: "study001",
          title: "My repertoire",
          label: "",
          category: "White",
          side: "white",
          enabled: true,
        },
      ];
    if (path === "/chapters") return [chapter];
    if (path === "/auth/status")
      return {
        authenticated: true,
        write: true,
        scopes: ["study:read", "study:write"],
      };
    if (path === "/backups") return [];
    if (path === "/training/progress") return { attempts: 2, correct: 1 };
    if (path.startsWith("/explorer"))
      return {
        position: "key",
        occurrences: [source],
        moves: [
          {
            uci: "e2e4",
            san: "e4",
            studies: 1,
            chapters: 1,
            occurrences: 1,
            references: [{ ...source, uci: "e2e4", san: "e4" }],
          },
        ],
      };
    if (path === "/chapters/study001/chapter1") return chapter;
    if (path.endsWith("/edit")) return { ...chapter, hash: "version2" };
    if (path.endsWith("/preview"))
      return {
        token: "review-token",
        status: "conflict",
        local_diff: "Local idea",
        remote_diff: "Remote idea",
        upload_diff: "Replacement",
        local: "1. e4 *",
        warning: "Whole chapter replacement",
        can_write: true,
      };
    if (path.startsWith("/training/next"))
      return {
        done: false,
        token: "exercise1",
        fen: START,
        chapter: "Berlin",
        study: "My repertoire",
      };
    if (path === "/training/answer")
      return {
        correct: true,
        moves: [{ uci: "e2e4", san: "e4", comment: "Prepared line", nags: [] }],
        due: "2026-10-12T00:00:00Z",
      };
    return {};
  });
});
afterEach(cleanup);
it("navigates the unified explorer without editing chapter content", async () => {
  render(<App />);
  await screen.findByText("Where this position lives");
  fireEvent.click(await screen.findByRole("button", { name: "e4 →" }));
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.some(
          ([path]) => path.includes("fen=") && path.includes("%20b%20"),
        ),
    ).toBe(true),
  );
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.endsWith("/edit")),
  ).toBe(false);
  expect(
    screen.getByText(
      "Counts describe occurrences in studies, not played games.",
    ),
  ).toBeVisible();
});
it("requires chapter selection and applies annotations to exactly that chapter", async () => {
  render(<App />);
  fireEvent.click(
    (await screen.findAllByRole("button", { name: "Berlin" }))[0],
  );
  await screen.findByText("Chapter workspace");
  fireEvent.change(screen.getByLabelText("Position comment"), {
    target: { value: "New comment" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save annotations locally" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/chapters/study001/chapter1/edit",
      expect.objectContaining({
        action: "annotate",
        comment: "New comment",
        expected_hash: "version1",
      }),
    ),
  );
});
it("blocks conflict upload until both review and overwrite are acknowledged", async () => {
  render(<App />);
  fireEvent.click(
    (await screen.findAllByRole("button", { name: "Berlin" }))[0],
  );
  await screen.findByText("Chapter workspace");
  fireEvent.click(
    screen.getByRole("button", { name: "Review synchronization" }),
  );
  const push = await screen.findByRole("button", {
    name: "Confirm push to Lichess",
  });
  expect(push).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText(
      "I reviewed the full chapter replacement and authorize this upload.",
    ),
  );
  expect(push).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText(
      "Keep local: explicitly overwrite the remote changes shown above.",
    ),
  );
  expect(push).toBeEnabled();
  expect(api).not.toHaveBeenCalledWith(
    expect.stringContaining("/push"),
    expect.anything(),
  );
});
it("training hides continuations before an answer and records only selected moves", async () => {
  render(<App />);
  await screen.findByText("Where this position lives");
  fireEvent.click(screen.getByRole("button", { name: /Training/ }));
  fireEvent.click(screen.getByRole("button", { name: "Start review" }));
  await screen.findByText(
    "Find a prepared continuation. Drag a piece or click its starting and destination squares.",
  );
  expect(screen.queryByText("Prepared line")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Square e2" }));
  fireEvent.click(screen.getByRole("button", { name: "Square e4" }));
  await screen.findByText("That’s in your repertoire.");
  expect(api).toHaveBeenCalledWith("/training/answer", {
    token: "exercise1",
    uci: "e2e4",
  });
});
it("shows network failures as actionable errors", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Lichess request timed out"));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Lichess request timed out",
  );
});
