"""Lossless supported PGN trees; node identity is a UCI path, not sibling order."""

import hashlib
import io
import json
import re

import chess
import chess.pgn

IDENTITY_TAGS = {
    "StudyName",
    "ChapterName",
    "ChapterURL",
    "Site",
    "Annotator",
    "UTCDate",
    "UTCTime",
}
IMMUTABLE_TAGS = IDENTITY_TAGS | {"FEN", "SetUp", "Variant", "Orientation"}
ID = re.compile(r"^[A-Za-z0-9]{8}$")
CHAPTER_URL = re.compile(
    r"https://lichess\.org/study/([A-Za-z0-9]{8})/([A-Za-z0-9]{8})(?:$|[?#])"
)


def parse(text: str) -> list[chess.pgn.Game]:
    if len(text) > 10_000_000:
        raise ValueError("PGN exceeds 10 MB limit")
    # python-chess ignores unrecognized tokens; refuse silently truncated PGNs.
    lex = re.sub(
        r'^\s*\[[A-Za-z][A-Za-z0-9_]*\s+"(?:[^"\\]|\\.)*"\]\s*$', "", text, flags=re.M
    )
    lex = re.sub(r";[^\n]*|^%[^\n]*", "", lex, flags=re.M)
    lex = re.sub(r"\{[^}]*\}", "", lex, flags=re.S)
    if "{" in lex or "}" in lex:
        raise ValueError("Unterminated or invalid PGN comment")
    balance = 0
    for char in lex:
        if char == "(":
            balance += 1
        elif char == ")":
            balance -= 1
        if balance < 0:
            raise ValueError("Unbalanced PGN variation")
    if balance:
        raise ValueError("Unbalanced PGN variation")
    lex = chess.pgn.MOVETEXT_REGEX.sub("", lex)
    lex = re.sub(r"\d+\.{1,3}|\s+", "", lex)
    if lex:
        raise ValueError("Unrecognized or malformed PGN text")
    stream = io.StringIO(text)
    games = []
    while (game := chess.pgn.read_game(stream)) is not None:
        if game.errors:
            raise ValueError("Invalid PGN: " + str(game.errors[0]))
        if game.headers.get("Variant", "Standard") not in {
            "Standard",
            "From Position",
            "Chess",
        }:
            raise ValueError(
                "Only standard chess and standard custom positions are supported"
            )
        if not game.board().is_valid():
            raise ValueError("Invalid starting position")
        # Do not accept python-chess's permissive handling of unknown tokens silently.
        for node, _ in walk(game):
            board = node.board()
            for child in node.variations:
                if child.move not in board.legal_moves:
                    raise ValueError("Illegal move in PGN")
        games.append(game)
    if not games:
        raise ValueError("PGN has no chapters")
    return games


def one(text: str) -> chess.pgn.Game:
    games = parse(text)
    if len(games) != 1:
        raise ValueError("Select exactly one chapter")
    return games[0]


def serialize(game):
    return game.accept(
        chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    )


def position_key(fen: str) -> str:
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("Invalid FEN position")
    # Counters are not position identity. EP is relevant only when capture is legal.
    return " ".join(board.fen(en_passant="legal").split()[:4])


def walk(game):
    stack = [(game, "")]
    while stack:
        node, path = stack.pop()
        yield node, path
        stack.extend(
            (v, (path + "/" + v.move.uci()).lstrip("/"))
            for v in reversed(node.variations)
        )


def at(game, path):
    node = game
    for uci in filter(None, path.split("/")):
        node = next((v for v in node.variations if v.move.uci() == uci), None)
        if node is None:
            raise ValueError("Node no longer exists; refresh the chapter")
    return node


def tree(game):
    rows = []
    for node, path in walk(game):
        rows.append(
            {
                "id": path,
                "parent": path.rsplit("/", 1)[0] if "/" in path else "",
                "fen": node.board().fen(),
                "san": node.san() if node.parent else "Start",
                "label": (
                    str(node.parent.board().fullmove_number)
                    + ("." if node.parent.board().turn else "…")
                    + " "
                    + node.san()
                )
                if node.parent
                else "Start",
                "uci": node.move.uci() if node.move else None,
                "depth": len(path.split("/")) if path else 0,
                "comment": node.comment,
                "starting_comment": node.starting_comment,
                "nags": sorted(node.nags),
                "children": [
                    (path + "/" + v.move.uci()).lstrip("/") for v in node.variations
                ],
            }
        )
    return rows


def semantic(game, include_tags=True):
    nodes = [
        {k: row[k] for k in ("id", "comment", "starting_comment", "nags", "children")}
        for row in tree(game)
    ]
    result = {"start": game.board().fen(), "nodes": nodes}
    if include_tags:
        result["tags"] = {
            k: v for k, v in game.headers.items() if k not in IDENTITY_TAGS
        }
    return result


def digest(text):
    return hashlib.sha256(
        json.dumps(semantic(one(text)), sort_keys=True).encode()
    ).hexdigest()


def chapter_identity(game, study_id):
    match = CHAPTER_URL.match(game.headers.get("ChapterURL", "")) or CHAPTER_URL.match(
        game.headers.get("Site", "")
    )
    if not match or match[1] != study_id:
        raise ValueError(
            "Export lacks a trustworthy chapter URL; refusing to invent a chapter ID"
        )
    return match[2]


def edit(text, action, path="", **args):
    game = one(text)
    node = at(game, path)
    if action == "add":
        move = chess.Move.from_uci(args["uci"])
        if move not in node.board().legal_moves:
            raise ValueError("Illegal move")
        if not any(v.move == move for v in node.variations):
            node.add_variation(move)
    elif action == "delete":
        if not node.parent:
            raise ValueError("Cannot delete chapter root")
        node.parent.remove_variation(node)
    elif action == "promote":
        if not node.parent:
            raise ValueError("Select a move")
        node.parent.promote_to_main(node)
    elif action == "reorder":
        order = args["order"]
        if sorted(order) != sorted(v.move.uci() for v in node.variations):
            raise ValueError("Order must include each child exactly once")
        node.variations[:] = [
            next(v for v in node.variations if v.move.uci() == u) for u in order
        ]
    elif action == "annotate":
        if any(c in args.get("comment", "") for c in "{}"):
            raise ValueError("Comments cannot contain PGN delimiters")
        node.comment = args.get("comment", node.comment)
        nags = args.get("nags", sorted(node.nags))
        if any(not isinstance(n, int) or not 0 <= n <= 255 for n in nags):
            raise ValueError("NAGs must be integers between 0 and 255")
        node.nags = set(nags)
    elif action == "tags":
        for key, value in args["tags"].items():
            if key in IMMUTABLE_TAGS or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
                raise ValueError(
                    "Source identity and starting-position tags cannot be edited"
                )
            if any(c in value for c in '\n\r"\\'):
                raise ValueError("Tag value contains unsupported characters")
            if value:
                game.headers[key] = value
            else:
                game.headers.pop(key, None)
    else:
        raise ValueError("Unknown edit operation")
    result = serialize(game)
    one(result)
    return result
