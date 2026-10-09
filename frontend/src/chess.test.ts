import { describe, expect, it } from "vitest";
import { legalMove, playUci, START } from "./chess";

describe("legal board navigation", () => {
  it("rejects illegal moves without changing position", () => {
    expect(legalMove(START, "e2", "e5")).toBeNull();
  });
  it("plays a continuation and updates turn", () => {
    const result = playUci(START, "e2e4");
    expect(result?.san).toBe("e4");
    expect(result?.fen.split(" ")[1]).toBe("b");
  });
  it("handles castling, en passant and underpromotion", () => {
    expect(playUci("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1")?.san).toBe(
      "O-O",
    );
    expect(playUci("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6")?.san).toBe(
      "exd6",
    );
    expect(playUci("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8n")?.uci).toBe(
      "a7a8n",
    );
  });
});
