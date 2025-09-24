from abc import ABC, abstractmethod
from typing import Tuple, List

class Alg3D(ABC):
    """
    3D四目アルゴリズムの親クラス
    学生はこのクラスを継承して get_move を実装する
    """

    @abstractmethod
    def get_move(self, board: List[List[List[int]]]) -> Tuple[int, int]:
        """
        次の手を返すメソッド
        board[z][y][x] 形式で石の配置が入る (0=空, 1=黒, 2=白)
        戻り値は (x, y) のタプル
        """
        pass

