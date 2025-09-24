from typing import Dict, List, Optional, Tuple
def create_board():
    """4x4x4の立体ボードを作成（z, y, x）
    z: 高さ（0が最下段）
    y: 奥行き（0が手前）
    x: 横方向（0が左）
    """
    return [[[0 for x in range(4)] for y in range(4)] for z in range(4)]


def place_disk(board, x, y, player):
    """
    指定された x, y の列に、下から順にプレイヤーのディスクを置く。
    成功すれば True、列がいっぱいなら False を返す。
    """
    for z in range(4):
        if board[z][y][x] == 0:
            board[z][y][x] = player
            return True
    return False


def generate_lines() -> List[List[Tuple[int, int, int]]]:
    directions = [
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 1, 0),
        (1, -1, 0),
        (1, 0, 1),
        (1, 0, -1),
        (0, 1, 1),
        (0, 1, -1),
        (1, 1, 1),
        (1, 1, -1),
        (1, -1, 1),
        (-1, 1, 1),
    ]
    lines: List[List[Tuple[int, int, int]]] = []
    for x in range(4):
        for y in range(4):
            for z in range(4):
                for dx, dy, dz in directions:
                    line: List[Tuple[int, int, int]] = []
                    for i in range(4):
                        nx, ny, nz = x + dx * i, y + dy * i, z + dz * i
                        if 0 <= nx < 4 and 0 <= ny < 4 and 0 <= nz < 4:
                            line.append((nx, ny, nz))
                        else:
                            break
                    if len(line) == 4:
                        lines.append(line)
    return lines


LINES = generate_lines()


def check_win_with_positions(board, player):
    """
    LINES方式で勝ち判定。
    プレイヤーが勝っている場合、その4つの駒の座標リストを返す。
    勝っていない場合は None。
    """
    for line in LINES:
        if all(board[z][y][x] == player for (x, y, z) in line):
            print(f"[DEBUG] Player {player} wins! coords={line}")
            return line
    return None


def check_win(board, player):
    """勝っているかどうかの真偽だけ返す"""
    return check_win_with_positions(board, player) is not None


def is_full(board):
    """盤面がすべて埋まっているかを確認"""
    return all(cell != 0 for layer in board for row in layer for cell in row)


# ゲーム状態（例として初期化しておく）
game_state = {
    "board": create_board(),
    "current_player": 1,
    "move_count": 0,
    "game_over": False
}
