# === framework.py（サーバー側のみ配置）===
from abc import ABC, abstractmethod
from typing import Tuple, List

Board = List[List[List[int]]]  # board[z][y][x]（0=空, 1=黒, 2=白）

class Alg3D(ABC):
    @abstractmethod
    def get_move(self, board: Board) -> Tuple[int, int]:
        """(x, y) を返す。0 <= x < 4, 0 <= y < 4"""
        ...
