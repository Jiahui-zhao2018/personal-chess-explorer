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


class ValidatingGameBuilder(chess.pgn.GameBuilder):
    """Let python-chess build the tree, validating the original SAN tokens."""

    def __init__(self, san_tokens):
        super().__init__()
        self.san_tokens = san_tokens

    def parse_san(self, board, san):
        # read_game's regex omits check/mate suffixes. The strict lexical pass
        # keeps them, in the same order that read_game visits moves/variations.
        original = next(self.san_tokens)
        label = f"{board.fullmove_number}{'.' if board.turn else '...'} {original}"
        try:
            move = board.parse_san(original)
        except chess.IllegalMoveError as error:
            raise ValueError(f"Illegal chess move at {label}: {error}") from error
        except chess.AmbiguousMoveError as error:
            raise ValueError(f"Ambiguous SAN at {label}: {error}") from error
        except chess.InvalidMoveError as error:
            raise ValueError(f"Malformed SAN at {label}: {error}") from error
        if move not in board.legal_moves:
            raise ValueError(f"Illegal chess move at {label}")
        if original.endswith(("+", "#")):
            result = board.copy()
            result.push(move)
            if original.endswith("#") and not result.is_checkmate():
                raise ValueError(
                    f"Incorrect checkmate suffix at {label}: move does not give checkmate"
                )
            if original.endswith("+") and not result.is_check():
                raise ValueError(
                    f"Incorrect check suffix at {label}: move does not give check"
                )
        return move

    def handle_error(self, error):
        # Fail immediately, rather than logging and returning a truncated tree.
        raise error


def parse(text: str) -> list[chess.pgn.Game]:
    if len(text) > 10_000_000:
        raise ValueError("PGN exceeds 10 MB limit")
    # python-chess ignores unrecognized tokens; refuse silently truncated PGNs.
    lex = re.sub(
        r'^\s*\[[A-Za-z][A-Za-z0-9_]*\s+"(?:[^"\\]|\\.)*"\]\s*$', "", text, flags=re.M
    )
    lex = re.sub(r";[^\n]*|^%[^\n]*", "", lex, flags=re.M)
    lex = re.sub(r"\{[^}]*\}", " ", lex, flags=re.S)
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
    san_tokens = []
    move_number = 1
    for token_match in re.finditer(r"\d+\.{1,3}|\$\d+|[()!?*]|[^\s()!?*$]+|\$", lex):
        token = token_match.group()
        if re.fullmatch(r"\d+\.{1,3}", token):
            move_number = int(token.split(".")[0])
            continue
        # Accept one suffix only on a library-recognized move, never on results
        # or annotations. Do not remove symbols globally or accept stray '+/#'.
        base = token[:-1] if token.endswith(("+", "#")) else token
        match = chess.pgn.MOVETEXT_REGEX.fullmatch(base)
        if not match or (base != token and not match.group(1)):
            raise ValueError(f"Malformed PGN syntax near move {move_number}: {token!r}")
        if match.group(1):
            san_tokens.append(token)
    original_sans = iter(san_tokens)
    stream = io.StringIO(text)
    games = []
    while (
        game := chess.pgn.read_game(
            stream, Visitor=lambda: ValidatingGameBuilder(original_sans)
        )
    ) is not None:
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
