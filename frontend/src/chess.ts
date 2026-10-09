import { Chess } from "chess.js";
export const START = new Chess().fen();
export function legalMove(
  fen: string,
  from: string,
  to: string,
  promotion = "q",
) {
  try {
    const game = new Chess(fen);
    const move = game.move({ from, to, promotion });
    return {
      fen: game.fen(),
      uci: move.from + move.to + (move.promotion || ""),
      san: move.san,
    };
  } catch {
    return null;
  }
}
export function playUci(fen: string, uci: string) {
  return legalMove(fen, uci.slice(0, 2), uci.slice(2, 4), uci[4] || "q");
}
