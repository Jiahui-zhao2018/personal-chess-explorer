import chess
import pytest

from app.pgn import (
    at,
    chapter_identity,
    digest,
    edit,
    one,
    parse,
    position_key,
    serialize,
    tree,
)
from conftest import pgn


def test_nested_variations_and_annotations_roundtrip():
    source = pgn(
        "1. e4 { [%clk 0:03:00] [%eval 0.25] plan } e5 (1... c5 $1 {Sicilian} 2. Nf3 (2. Nc3 $14)) 2. Nf3 *"
    )
    game = one(source)
    rows = tree(game)
    assert len(rows) == 7
    assert at(game, "e2e4/c7c5/b1c3").nags == {14}
    assert "Sicilian" in at(game, "e2e4/c7c5").comment
    assert "[%clk" in at(game, "e2e4").comment
    assert digest(source) == digest(serialize(game))


def test_multiple_chapters_and_stable_identity():
    games = parse(pgn() + "\n" + pgn("1. d4 *", cid="chapter2"))
    assert [chapter_identity(g, "study001") for g in games] == ["chapter1", "chapter2"]
    with pytest.raises(ValueError):
        chapter_identity(games[0], "study002")


def test_custom_fen():
    fen = "8/8/8/8/8/4k3/8/4K3 w - - 0 1"
    game = one(pgn("1. Kf1 *", extra=f'[SetUp "1"]\n[FEN "{fen}"]'))
    assert game.board().fen() == fen
    assert len(tree(game)) == 2


def test_transposition_identity_counters_and_en_passant():
    a = chess.Board()
    b = chess.Board()
    for move in ["Nf3", "Nf6", "g3", "g6"]:
        a.push_san(move)
    for move in ["g3", "g6", "Nf3", "Nf6"]:
        b.push_san(move)
    assert a.fen() != b.fen()
    assert position_key(a.fen()) == position_key(b.fen())
    a = chess.Board()
    a.push_san("e4")
    assert position_key(a.fen(en_passant="fen")) == position_key(a.fen())
    a = chess.Board()
    for move in ["e4", "a6", "e5", "d5"]:
        a.push_san(move)
    assert position_key(a.fen()).endswith("d6")
    assert position_key(a.fen()) != position_key(a.fen().replace("d6", "-"))


@pytest.mark.parametrize(
    "moves", ["1. e4 e4 *", "1. e9 *", "1. e4 JUNK *", "1. e4 {unterminated *"]
)
def test_reject_invalid_pgn(moves):
    with pytest.raises(ValueError):
        one(pgn(moves))


def test_add_delete_promote_reorder_keep_siblings_and_comments():
    source = pgn()
    added = edit(source, "add", "e2e4", uci="e7e6")
    assert len(at(one(added), "e2e4").variations) == 3
    assert at(one(added), "e2e4/c7c5").comment == "Sicilian"
    promoted = edit(added, "promote", "e2e4/e7e6")
    assert at(one(promoted), "e2e4").variations[0].move.uci() == "e7e6"
    reordered = edit(promoted, "reorder", "e2e4", order=["c7c5", "e7e5", "e7e6"])
    assert at(one(reordered), "e2e4").variations[0].move.uci() == "c7c5"
    deleted = edit(reordered, "delete", "e2e4/e7e6")
    assert len(at(one(deleted), "e2e4").variations) == 2
    assert digest(source) != digest(deleted)  # ordering is meaningful


def test_edit_tags_and_starting_comments():
    source = pgn("1. e4 e5 ( {Alternative intro} 1... c5 {After move}) *")
    assert at(one(source), "e2e4/c7c5").starting_comment == "Alternative intro"
    result = edit(source, "tags", tags={"Opening": "Sicilian"})
    assert one(result).headers["Opening"] == "Sicilian"
    assert digest(result) == digest(serialize(one(result)))
    with pytest.raises(ValueError):
        edit(result, "tags", tags={"ChapterURL": "wrong"})
    with pytest.raises(ValueError):
        edit(result, "add", "", uci="e2e5")
    with pytest.raises(ValueError):
        edit(result, "annotate", "", comment="unsafe } text")


CHECK_FEN = "4k3/8/8/8/1N6/5P2/7n/4K3 w - - 0 17"
MATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"


def from_position(fen, moves):
    return pgn(moves, extra=f'[SetUp "1"]\n[FEN "{fen}"]')


@pytest.mark.parametrize(
    "moves",
    [
        "17. Nc6 Nxf3+",
        "17. Nc6 Nxf3",
        "17. Nc6",
        "17. Nc6 Nxf3+ *",
        "17.\t Nc6  \n   Nxf3+  ",
        "17. Nc6 {A quiet move} (17. Na6 {Alternative} Nxf3+ $1) Nxf3+ {Check!}",
        "17.Nc6{A quiet move}(17.Na6)Nxf3+$1*",
    ],
)
def test_check_suffix_and_incomplete_games_roundtrip(moves):
    game = one(from_position(CHECK_FEN, moves))
    exported = serialize(game)
    assert digest(exported) == digest(serialize(one(exported)))
    if "Nxf3" in moves:
        assert game.end().san() == "Nxf3+"
        assert "Nxf3+" in exported
        assert game.end().board().is_check()
    if "Alternative" in moves:
        alternative = at(game, "b4a6/h2f3")
        assert alternative.san() == "Nxf3+" and alternative.nags == {1}
        assert alternative.parent.comment == "Alternative"


@pytest.mark.parametrize("san", ["Qh7#", "Qh7"])
def test_checkmate_suffix_is_preserved_and_generated(san):
    game = one(from_position(MATE_FEN, "1. " + san))
    assert game.end().board().is_checkmate()
    assert game.end().san() == "Qh7#"
    assert "Qh7#" in serialize(game)
    assert digest(serialize(game)) == digest(serialize(one(serialize(game))))


def test_queen_check_from_standard_start():
    game = one("1. e4 f6 2. Qh5+")
    assert game.end().san() == "Qh5+"
    assert game.end().board().is_check()


@pytest.mark.parametrize(
    "moves,expected",
    [
        ("17. Nc6+", "Incorrect check suffix at 17. Nc6+"),
        ("17. Nc6 Nxf3#", "Incorrect checkmate suffix at 17... Nxf3#"),
        ("17. Nc6 Nxf4+", "Illegal chess move at 17... Nxf4+"),
        ("17. Nc9", "Malformed PGN syntax near move 17: 'Nc9'"),
        ("17. Nc6 Nxf3++", "Malformed PGN syntax near move 17: 'Nxf3++'"),
        ("17. Nc6 #", "Malformed PGN syntax near move 17: '#'"),
    ],
)
def test_suffix_and_move_errors_are_specific(moves, expected):
    with pytest.raises(ValueError) as error:
        one(from_position(CHECK_FEN, moves))
    assert expected in str(error.value)


def test_illegal_move_inside_variation_identifies_actual_move_number():
    with pytest.raises(ValueError, match=r"Illegal chess move at 17\.\.\. Nxf4\+"):
        one(from_position(CHECK_FEN, "17. Nc6 (17. Na6 Nxf4+) Nxf3+"))


def test_multiple_chapters_keep_suffix_tokens_aligned():
    games = parse(
        from_position(CHECK_FEN, "17. Nc6 Nxf3+")
        + "\n\n"
        + from_position(MATE_FEN, "1. Qh7#")
    )
    assert [game.end().san() for game in games] == ["Nxf3+", "Qh7#"]
