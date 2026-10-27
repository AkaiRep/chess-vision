"""From recognised cells to a full chess position.

- Orientation: "my" side is always at the bottom. Read from the rank labels if possible,
  otherwise from where the white king (or the bulk of the white pieces) stands.
- Side to move: mine by default. A highlighted last move confirms it, or triggers a warning
  if it was my own piece that moved.
- Castling rights: king and rook on their original squares. En passant: from the last move.
- Validation with python-chess; invalid positions are reported, not analysed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from server.board_locator import SquareShade
from server.recognizer import EMPTY, Recognition

STATUS_MESSAGES: dict[int, str] = {
    chess.STATUS_NO_WHITE_KING: "нет белого короля",
    chess.STATUS_NO_BLACK_KING: "нет чёрного короля",
    chess.STATUS_TOO_MANY_KINGS: "больше одного короля одного цвета",
    chess.STATUS_TOO_MANY_WHITE_PAWNS: "больше 8 белых пешек",
    chess.STATUS_TOO_MANY_BLACK_PAWNS: "больше 8 чёрных пешек",
    chess.STATUS_PAWNS_ON_BACKRANK: "пешка на крайней горизонтали",
    chess.STATUS_TOO_MANY_WHITE_PIECES: "больше 16 белых фигур",
    chess.STATUS_TOO_MANY_BLACK_PIECES: "больше 16 чёрных фигур",
    chess.STATUS_OPPOSITE_CHECK: "шах королю стороны, которая не ходит (смените сторону хода?)",
    chess.STATUS_TOO_MANY_CHECKERS: "невозможный шах (слишком много атакующих)",
    chess.STATUS_IMPOSSIBLE_CHECK: "невозможный шах",
}

CASTLING = (
    (chess.E1, chess.H1, chess.WHITE, chess.ROOK),
    (chess.E1, chess.A1, chess.WHITE, chess.ROOK),
    (chess.E8, chess.H8, chess.BLACK, chess.ROOK),
    (chess.E8, chess.A8, chess.BLACK, chess.ROOK),
)


def color_name(color: chess.Color) -> str:
    return "белые" if color == chess.WHITE else "чёрные"


def screen_to_square(row: int, col: int, flipped: bool) -> chess.Square:
    """Screen cell (row 0 = top) -> chess square. flipped = black at the bottom."""
    return chess.square(7 - col, row) if flipped else chess.square(col, 7 - row)


def square_to_screen(square: chess.Square, flipped: bool) -> tuple[int, int]:
    file, rank = chess.square_file(square), chess.square_rank(square)
    return (rank, 7 - file) if flipped else (7 - rank, file)


def flipped_by_pieces(labels: list[list[str]]) -> bool:
    """Fallback orientation: white king in the top half -> black is at the bottom."""
    for r, row in enumerate(labels):
        for label in row:
            if label == "K":
                return r < 4
    for r, row in enumerate(labels):
        for label in row:
            if label == "k":
                return r >= 4
    white = [r for r, row in enumerate(labels) for label in row if label.isupper()]
    black = [r for r, row in enumerate(labels) for label in row if label.islower()]
    if white and black:
        return sum(white) / len(white) < sum(black) / len(black)
    return False


@dataclass
class Position:
    board: chess.Board
    flipped: bool  # True = black at the bottom
    my_color: chess.Color
    orientation_source: str  # "labels", "pieces" or "manual"
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    last_move: tuple[chess.Square, chess.Square] | None = None
    suspicious: list[chess.Square] = field(default_factory=list)

    @property
    def fen(self) -> str:
        return self.board.fen(en_passant="legal")


def _last_move(
    recognition: Recognition, board: chess.Board, flipped: bool
) -> tuple[chess.Square, chess.Square] | None:
    marked = [
        screen_to_square(r, c, flipped)
        for r, row in enumerate(recognition.cells)
        for c, cell in enumerate(row)
        if cell.shade is SquareShade.OTHER
    ]
    if len(marked) != 2:
        return None
    occupied = [sq for sq in marked if board.piece_at(sq)]
    if len(occupied) != 1:
        return None  # castling with both squares re-occupied etc.: not decisive
    to_sq = occupied[0]
    from_sq = marked[0] if marked[1] == to_sq else marked[1]
    return from_sq, to_sq


def _en_passant(board: chess.Board, last_move: tuple[chess.Square, chess.Square]) -> chess.Square | None:
    from_sq, to_sq = last_move
    piece = board.piece_at(to_sq)
    if piece is None or piece.piece_type != chess.PAWN or piece.color == board.turn:
        return None
    if chess.square_file(from_sq) != chess.square_file(to_sq):
        return None
    start, double = (1, 3) if piece.color == chess.WHITE else (6, 4)
    if chess.square_rank(from_sq) != start or chess.square_rank(to_sq) != double:
        return None
    return chess.square(chess.square_file(to_sq), (start + double) // 2)


def build_position(
    recognition: Recognition,
    flipped_by_labels: bool | None,
    flip: bool = False,
    switch_turn: bool = False,
) -> Position:
    """flip / switch_turn are the manual overrides from the UI buttons."""
    labels = recognition.labels()
    if flipped_by_labels is not None:
        flipped, source = flipped_by_labels, "labels"
    else:
        flipped, source = flipped_by_pieces(labels), "pieces"
    if flip:
        flipped, source = not flipped, "manual"
    my_color = chess.BLACK if flipped else chess.WHITE

    board = chess.Board(None)
    for r, row in enumerate(labels):
        for c, label in enumerate(row):
            if label != EMPTY:
                board.set_piece_at(screen_to_square(r, c, flipped), chess.Piece.from_symbol(label))
    board.turn = my_color if not switch_turn else not my_color

    rights = chess.BB_EMPTY
    for king_sq, rook_sq, color, _ in CASTLING:
        if board.piece_at(king_sq) == chess.Piece(chess.KING, color) and board.piece_at(rook_sq) == chess.Piece(
            chess.ROOK, color
        ):
            rights |= chess.BB_SQUARES[rook_sq]
    board.castling_rights = rights

    warnings: list[str] = []
    last_move = _last_move(recognition, board, flipped)
    if last_move:
        mover = board.piece_at(last_move[1])
        assert mover is not None
        if mover.color == board.turn:
            warnings.append(
                f"Последний ход сделали {color_name(mover.color)}, а ход сейчас у них же — "
                "проверьте сторону хода."
            )
        else:
            ep = _en_passant(board, last_move)
            if ep is not None:
                board.ep_square = ep
                if not board.has_legal_en_passant():
                    board.ep_square = None

    suspicious = [screen_to_square(r, c, flipped) for r, c in recognition.suspicious()]
    if suspicious:
        names = ", ".join(chess.square_name(sq) for sq in suspicious)
        warnings.append(f"Не уверен в клетках: {names}")

    status = board.status()
    errors = [msg for flag, msg in STATUS_MESSAGES.items() if status & flag]
    if status and not errors:
        errors.append("некорректная позиция")
    return Position(
        board=board,
        flipped=flipped,
        my_color=my_color,
        orientation_source=source,
        valid=status == chess.STATUS_VALID,
        errors=errors,
        warnings=warnings,
        last_move=last_move,
        suspicious=suspicious,
    )
