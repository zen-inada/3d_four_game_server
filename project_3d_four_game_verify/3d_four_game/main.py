# uuid main.py (FastAPI) — サーバー/フロント/静的ファイル クリーン版
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import importlib.util
import traceback
import copy
import sys
import uuid
import logging
import secrets, string
from typing import Dict, List, Optional, Tuple
from uuid import uuid4
from fastapi import HTTPException
from typing import Optional
import json, subprocess, sys
import multiprocessing as mp
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime, timezone
import json, os, tempfile
from fastapi import Response, status

# ゲームロジック（必要なものだけインポート）
from backend.game_logic import (
    create_board,
    is_full,
)

# --- locking (robust import with fallback) ---
try:
    from filelock import FileLock  # pip install filelock
except Exception:
    # フォールバック（同一プロセスのみ。複数プロセス時は本物のfilelockを使ってね）
    class FileLock:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False


# ========== ログ ==========
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

WORKER_PATH = Path(__file__).resolve().parent / "worker_algo.py"

# ========== パス定義 ==========
BASE_DIR = Path(__file__).resolve().parent  # .../3d_four_game
ROOT = BASE_DIR.parent  # .../project_3d_four_game

ALGO_DIR = ROOT
EXTRA_DIRS = [ALGO_DIR]

# ========== FastAPI ==========
app = FastAPI()

# フロント
app.mount(
    "/app", StaticFiles(directory=BASE_DIR / "frontend", html=True), name="frontend"
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend/static"), name="static")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 追加ルーター（リポジトリクローン等）
from main_server.clone_repo import router as clone_router

app.include_router(clone_router)


# ========== ユーティリティ ==========
# main.py の load_algo_module_flexible を差し替え（または中身を追加）
def load_algo_module_flexible(algo: str):
    """
    algo は:
      - *.py へのパス
      - ディレクトリ（中の main.py）
      - 別名（BASE_DIR/別名/main.py）
    に対応。さらに実行時だけ当該ディレクトリを sys.path に追加して相対インポートを通す。
    """
    if not algo or not str(algo).strip():
        raise HTTPException(status_code=400, detail="algorithmPath が空です")

    s = str(algo).strip().replace("\\", "/")
    p = Path(s)
    tried = []

    if p.suffix.lower() == ".py":
        tried.append(str(p))
        target = p if p.exists() else None
        mod_dir = p.parent if target else None
    else:
        target = None
        mod_dir = None
        if p.is_absolute():
            cand = p / "main.py"
            tried.append(str(cand))
            if cand.exists():
                target = cand
                mod_dir = cand.parent
        else:
            cand1 = BASE_DIR / p / "main.py"
            tried.append(str(cand1))
            if cand1.exists():
                target = cand1
                mod_dir = cand1.parent
            if target is None and p.suffix.lower() == ".py":
                cand2 = BASE_DIR / p
                tried.append(str(cand2))
                if cand2.exists():
                    target = cand2
                    mod_dir = cand2.parent

    if target is None:
        raise HTTPException(
            status_code=400,
            detail=f"[resolve_algo] 'main.py' が見つかりません。候補: {tried}",
        )

    mod_name = f"algo_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(mod_name, str(target))
    if not spec or not spec.loader:
        raise HTTPException(status_code=500, detail=f"spec を作成できません: {target}")

    # ★ 当該フォルダを一時的に sys.path へ
    import sys

    added = False
    if mod_dir:
        mod_dir_str = str(mod_dir.resolve())
        if mod_dir_str not in sys.path:
            sys.path.insert(0, mod_dir_str)
            added = True
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if added:
            try:
                sys.path.remove(mod_dir_str)
            except ValueError:
                pass
    return module


def resolve_algo(algo_name: str) -> str:
    """
    AI名 → 実際の main.py へのパスを返す（必要に応じて編集）
    """
    table = {
        "main": "/home/ec2-user/project_3d_four_game/main.py",
        "strong_ai": "/home/ec2-user/project_3d_four_game/strong_ai/main.py",
        "poniponi": "/home/ec2-user/project_3d_four_game/poni-arg-poniponi/main.py",
    }
    if algo_name in table:
        return table[algo_name]
    raise ValueError(f"Unknown algo name: {algo_name}")


def load_algo_module(algo_path: str):
    """
    指定された main.py のファイルパスから Python モジュールをロードして返す。
    """
    module_name = f"algo_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, algo_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {algo_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_move(self, x: int, y: int):
    if self.game_over:
        return {"status": "finished", **self.state_dict()}

    placed = place_disk(self.board, x, y, self.current_player)
    if not placed:
        return {"status": "invalid", **self.state_dict()}

    self.move_count += 1
    coords = check_win_with_positions(self.board, self.current_player)

    if _really_won(self.board, self.current_player, coords):
        self.game_over = True
        out = {
            "status": "win",
            "winner": self.current_player,
            "player": f"Player {self.current_player}",
            "winning_coords": coords,
            **self.state_dict(),
            "last_move": {"x": x, "y": y},
        }
        # 🔥 終了したら games から削除
        for gid, g in list(games.items()):
            if g is self:
                del games[gid]
                break
        return out


# 追加：左上（y→x）から最初に入る (x,y) を探す
def _first_empty_xy(board) -> Optional[Tuple[int, int]]:
    for y in range(4):
        for x in range(4):
            for z in range(4):
                if board[z][y][x] == 0:
                    return (x, y)
    return None


# ------- ベア名→実体解決（既存の resolve_algo を生かしつつ柔軟化） -------
def resolve_algo_path(algo_id_or_path: str) -> str:
    """
    既存の resolve_algo がある場合はそれを優先。
    それで解決できない場合は flexible に推測する。
    """
    s = (algo_id_or_path or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="algorithmPath が空です")

    # まずは既存のルール（例: DB/設定のエイリアス解決）
    try:
        # 既存の resolve_algo が 'strong_ai' → '/path/to/strong_ai' のように返す想定
        resolved = str(resolve_algo(s))
        if resolved:
            return resolved
    except Exception:
        # 既存関数で解決できないケースは無視して次へ
        pass

    # 既存解決がダメなら、そのまま flexible に処理できるよう返す
    return s


def generate_game_id(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ========== 3D四目判定（統一版） ==========
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


def check_win_with_positions(board: List[List[List[int]]], player: int):
    for line in LINES:
        if all(board[z][y][x] == player for (x, y, z) in line):
            return line
    return None


def _really_won(
    board: List[List[List[int]]],
    player: int,
    coords: Optional[List[Tuple[int, int, int]]],
) -> bool:
    if not coords or len(coords) != 4:
        return False
    try:
        for x, y, z in coords:
            if not (0 <= x < 4 and 0 <= y < 4 and 0 <= z < 4):
                return False
            if board[z][y][x] != player:
                return False
        return True
    except Exception:
        return False


def place_disk(board: List[List[List[int]]], x: int, y: int, player: int) -> bool:
    """最下段から積む"""
    for z in range(4):
        if board[z][y][x] == 0:
            board[z][y][x] = player
            return True
    return False


def _fmt_fail(kind: str, fe: str) -> str:
    """
    kind: 'timeout' | 'abnormal' | 'invalid'
    fe  : 強制配置した座標（例: '(0, 0)'）
    """
    MAP = {
        "timeout": "時間内に応答しなかったため、{fe}に強制配置",
        "abnormal": "異常終了したため、 {fe}に強制配置",
        "invalid": "無効座標を返したため、 {fe}に強制配置",
    }
    tpl = MAP.get(kind, "{fe}")
    return tpl.replace("{fe}", fe)


# ==== 追加（import群の下あたり）====
class InvalidMoveError(ValueError):
    """無効座標指定（形式不正・範囲外など）"""

    pass


class AISubprocessTimeout(TimeoutError):
    """タイムアウト"""

    pass


class AISubprocessCrashed(RuntimeError):
    """処理異常終了（非ゼロ終了コードなど）"""

    pass


# ---- 失敗メッセージ（3分類）を絶対にこの3文だけにする共通フォーマッタ ----
def _fmt_fail(kind: str, fe: str) -> str:
    """
    kind: 'timeout' | 'abnormal' | 'invalid'
    fe  : 強制配置した座標（例: '(0, 0)'）
    """
    MAP = {
        "timeout": "時間内に応答しなかったため、{fe}に強制配置",
        "abnormal": "異常終了したため、 {fe}に強制配置",
        "invalid": "無効座標を返したため、 {fe}に強制配置",
    }
    return MAP.get(kind, "{fe}").replace("{fe}", fe)


# ==== 置き換え（寛容版：失敗でもフォールバックして reason を返す）====
from typing import Tuple, Optional


def run_get_move_subprocess(
    algo_path: str, board: list, timeout: float = 29.0
) -> Tuple[int, int, Optional[str]]:
    """
    子プロセスで get_move を実行し (x, y) を返す。
    失敗時も対戦を止めず、左上(y→x)の空きセルにフォールバックして
    下記3分類のいずれかの定型文だけを reason に入れて返す。

      - timeout  : 「時間内に応答しなかったため、(x, y)に強制配置」
      - abnormal : 「異常終了したため、 (x, y)に強制配置」
      - invalid  : 「無効座標を返したため、 (x, y)に強制配置」
    """
    py = sys.executable
    p = subprocess.Popen(
        [py, str(WORKER_PATH), algo_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = p.communicate(json.dumps(board), timeout=timeout)
    except subprocess.TimeoutExpired:
        # ---- タイムアウト → 座標を決めて定型文のみ ----
        try:
            p.kill()
            p.wait(timeout=0.5)
        except Exception:
            pass
        x, y = _first_empty_xy(board) or (0, 0)
        return (x, y, _fmt_fail("timeout", f"({x}, {y})"))

    # ---- 非ゼロ終了コード = 処理異常終了（詳細は出さない）----
    if p.returncode != 0:
        x, y = _first_empty_xy(board) or (0, 0)
        return (x, y, _fmt_fail("abnormal", f"({x}, {y})"))

    # ---- 正常終了：出力の形式/範囲を検証。失敗は「invalid」に統一 ----
    try:
        move = json.loads(out or "{}")
        x, y = int(move["x"]), int(move["y"])
        if not (0 <= x < 4 and 0 <= y < 4):
            raise InvalidMoveError(f"out of range: ({x}, {y})")
        return (x, y, None)
    except Exception:
        x, y = _first_empty_xy(board) or (0, 0)
        return (x, y, _fmt_fail("invalid", f"({x}, {y})"))


# ==== 置き換え（厳格版：失敗は例外で上位に伝える）====
def run_get_move_subprocess_strict(
    algo_path: str, board: list, timeout: float = 29.0
) -> tuple[int, int]:
    py = sys.executable
    p = subprocess.Popen(
        [py, str(WORKER_PATH), algo_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = p.communicate(json.dumps(board), timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            p.kill()
            p.wait(timeout=0.5)
        except Exception:
            pass
        # ① タイムアウト
        raise AISubprocessTimeout("timeout")

    # ② 処理異常終了（詳細は上位で使わないため固定文言でOK）
    if p.returncode != 0:
        raise AISubprocessCrashed("abnormal")

    # ③ 正常終了でも (x,y) の形式・範囲を厳格に検証 → 不正は invalid 扱い
    try:
        move = json.loads(out or "{}")
        x = int(move.get("x"))
        y = int(move.get("y"))
        if not (0 <= x < 4 and 0 <= y < 4):
            raise InvalidMoveError(f"move out of range: ({x}, {y})")
        return (x, y)
    except InvalidMoveError:
        raise
    except Exception as e:
        # キー欠落/型不正/JSON不正などもここに寄せる
        raise InvalidMoveError(f"invalid move: {e}")


# ========== グローバル（/board, /reset 用の簡易ボード） ==========
global_board = create_board()
global_current_player = 1
global_game_over = False
global_move_count = 0
global_auto_p1 = ""
global_auto_p2 = ""


# ========== モデル ==========
class AlgoMoveRequest(BaseModel):
    player_id: str
    board: list
    algorithmPath: Optional[str] = None
    timeLimit: Optional[float] = None


class AutoStepBody(BaseModel):
    player1: str  # 例: "strong_ai"
    player2: str  # 例: "strong_ai"
    timeLimit: Optional[float] = None


class NewGameOut(BaseModel):
    game_id: str
    state: dict


class MoveIn(BaseModel):
    x: int
    y: int


# ========== ゲーム箱 ==========
class Game:
    def __init__(self, board_size: int = 4):
        self.board = create_board()  # 3D初期化
        self.current_player = 1
        self.game_over = False
        self.move_count = 0

    def state_dict(self):
        return {
            "board": copy.deepcopy(self.board),
            "current_player": self.current_player,
            "game_over": self.game_over,
            "move_count": self.move_count,
        }

    def make_move(self, x: int, y: int):
        if self.game_over:
            return {"status": "finished", **self.state_dict()}

        placed = place_disk(self.board, x, y, self.current_player)
        if not placed:
            return {"status": "invalid", **self.state_dict()}

        self.move_count += 1
        coords = check_win_with_positions(self.board, self.current_player)

        if _really_won(self.board, self.current_player, coords):
            self.game_over = True
            winplayer: int = self.current_player
            self.current_player = 3 - self.current_player
            out = {
                "status": "win",
                "winner": winplayer,
                "player": f"Player {winplayer}",
                "winning_coords": coords,
                **self.state_dict(),
                "last_move": {"x": x, "y": y},
            }
            return out

        if is_full(self.board):
            state = self.state_dict()
            state.update(
                {
                    "status": "draw",
                    "last_move": {"x": x, "y": y},
                }
            )
            return state

        # 継続
        self.current_player = 3 - self.current_player
        return {"status": "ok", **self.state_dict(), "last_move": {"x": x, "y": y}}


# ========== ゲームレジストリ ==========
games: Dict[str, Game] = {}


# ========== エンドポイント（グローバル簡易） ==========
@app.get("/board")
def get_board():
    return {
        "board": global_board,
        "current_player": global_current_player,
        "game_over": global_game_over,
        "move_count": global_move_count,
    }


@app.post("/reset")
def reset_board():
    global global_board, global_current_player, global_game_over, global_move_count, global_auto_p1, global_auto_p2
    global_board = create_board()
    global_current_player = 1
    global_game_over = False
    global_move_count = 0
    global_auto_p1 = ""
    global_auto_p2 = ""
    return {"status": "ok"}


# ========== エンドポイント（ゲームID制） ==========
@app.post("/games")
def create_game():
    game_id = str(uuid.uuid4())
    games[game_id] = Game(4)
    return {"game_id": game_id}


@app.get("/games/{game_id}")
def get_state(game_id: str):
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Invalid game_id")
    return game.state_dict()


@app.post("/games/{game_id}/move")
def move(game_id: str, payload: MoveIn):
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Invalid game_id")
    return game.make_move(payload.x, payload.y)


@app.delete("/games/{game_id}")
def delete_game(game_id: str):
    if game_id in games:
        del games[game_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Invalid game_id")


@app.post("/games/{game_id}/algo-move")
def algo_move_for_game(game_id: str, req: AlgoMoveRequest):
    """
    ステップ実行用：AIが正常に (x, y) を返せたときだけ move を返す。
    タイムアウト/実行失敗時は座標を捏造せず HTTP エラーを返す。
    """
    try:
        game = games.get(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Invalid game_id")

        # エイリアス/パス解決
        algo_path = req.algorithmPath or str(resolve_algo(req.player_id))

        # 20秒思考AIに対応できるよう余裕を持ったタイムアウト
        # ※ ここを 25.0 にしておくと 20秒sleep でもOK
        # UIから送られてきた timeLimit を優先、未指定なら30秒
        timeout = float(req.timeLimit or 30.0)
        x, y, reason = run_get_move_subprocess(algo_path, req.board, timeout=timeout)

        # 最低限のバリデーション（4x4）
        if not (0 <= x < 4 and 0 <= y < 4):
            raise HTTPException(
                status_code=400, detail=f"AIが不正な座標を返しました: ({x}, {y})"
            )

        return {"status": "ok", "move": {"x": x, "y": y}, "reason": reason}
    except TimeoutError as te:
        # ← タイムアウト時は座標を返さない（左上に置かない）
        raise HTTPException(status_code=408, detail=f"AIタイムアウト: {te}")
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        # ← 実行系の失敗も座標を返さない
        raise HTTPException(status_code=400, detail=f"AI実行エラー: {e}")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"アルゴリズム実行中にエラー: {e}")


# ========== /games/{id}/auto-step（AI vs AI を1手だけ進める） ==========
@app.post("/games/{game_id}/auto-step")
def auto_step_game(game_id: str, body: AutoStepBody):
    try:
        game = games.get(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Invalid game_id")
        if game.game_over:
            state = game.state_dict()
            state.update({"status": "finished"})
            return state

        cp = game.current_player
        raw_algo = body.player1 if cp == 1 else body.player2

        # 失敗カテゴリ（None なら成功）
        reason_kind: Optional[str] = None  # 'timeout' | 'abnormal' | 'invalid'
        x = y = None

        # --- AI 実行 ---
        if not raw_algo:
            # AI 未指定は abnormal 扱い
            reason_kind = "abnormal"
        else:
            algo_id_or_path = resolve_algo_path(raw_algo)
            try:
                # ★ UIで指定したtimeLimitを使う。未指定なら30秒。
                # ★ UIから送られてきた timeLimit を優先。未指定なら30秒。
                timeout = float(body.timeLimit or 30.0)
                logger.info(
                    f"[auto-step] body.timeLimit={body.timeLimit}, timeout={timeout}"
                )
                x, y = run_get_move_subprocess_strict(
                    algo_id_or_path, game.board, timeout=timeout
                )

            except AISubprocessTimeout:
                reason_kind = "timeout"
            except AISubprocessCrashed:
                reason_kind = "abnormal"
            except InvalidMoveError:
                reason_kind = "invalid"

        # --- 座標のバリデーション（厳格）：範囲外は invalid へ寄せる ---
        if reason_kind is None:
            try:
                if not (0 <= int(x) < 4 and 0 <= int(y) < 4):
                    raise InvalidMoveError()
                x, y = int(x), int(y)
            except Exception:
                reason_kind = "invalid"

        # --- フォールバック座標の決定 ---
        if reason_kind is not None:
            fe = _first_empty_xy(game.board)
            if fe is None:
                # 置ける場所がない → 引き分け。その上で (0,0) を last_move に載せる
                game.game_over = True
                game.move_count += 1
                state = game.state_dict()
                state.update(
                    {
                        "status": "draw",
                        "last_move": {"x": 0, "y": 0},
                        "reason": _fmt_fail(reason_kind, "(0, 0)"),
                    }
                )
                return state
            x, y = fe  # 左上(y→x)の空きセル
        # reason は最後にまとめて作る
        reason = _fmt_fail(reason_kind, f"({x}, {y})") if reason_kind else None

        # --- 実際に配置。指定列が満杯なら invalid として強制配置 ---
        if not place_disk(game.board, x, y, cp):
            placed = False
            for yy in range(4):
                for xx in range(4):
                    if place_disk(game.board, xx, yy, cp):
                        x, y = xx, yy
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                # 本当に置けない → 引き分け（(0,0)で固定メッセージ）
                game.game_over = True
                game.move_count += 1
                state = game.state_dict()
                state.update(
                    {
                        "status": "draw",
                        "last_move": {"x": 0, "y": 0},
                        "reason": _fmt_fail(reason_kind or "invalid", "(0, 0)"),
                    }
                )
                return state
            # 列が満杯だったので invalid に寄せる（成功済みでもメッセージは invalid）
            reason = _fmt_fail("invalid", f"({x}, {y})")

        # --- 勝敗/継続の判定 ---
        game.move_count += 1
        coords = check_win_with_positions(game.board, cp)

        if _really_won(game.board, cp, coords):
            game.current_player = 3 - cp
            state = game.state_dict()
            state.update(
                {
                    "status": "win",
                    "winner": cp,
                    "player": f"Player {cp}",
                    "winning_coords": coords,
                    "last_move": {"x": x, "y": y},
                }
            )
            if reason:
                state["reason"] = reason
            return state

        if is_full(game.board):
            state = game.state_dict()
            state.update(
                {
                    "status": "draw",
                    "last_move": {"x": x, "y": y},
                }
            )
            if reason:
                state["reason"] = reason
            return state

        # 次手へ
        game.current_player = 3 - cp
        state = game.state_dict()
        state.update(
            {
                "status": "ok",
                "last_move": {"x": x, "y": y},
            }
        )
        if reason:
            state["reason"] = reason
        return state

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"アルゴリズム実行中にエラー: {e}")


USERFILE = "/home/ec2-user/project_3d_four_game_verify/clone_algo/userlist.json"
USERLOCK = USERFILE + ".lock"

def _now():
    return datetime.now(timezone.utc).isoformat()


def _to_dict(model):
    # Pydantic v2 は model_dump、v1 は dict
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class User(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1)  # クローンされたアルゴの dir か main.py
    createdAt: str
    updatedAt: str


class UserStore(BaseModel):
    version: int = 1
    updatedAt: str
    users: List[User] = Field(default_factory=list)


def _read_store() -> UserStore:
    if not os.path.exists(USERFILE):
        s = UserStore(version=1, updatedAt=_now(), users=[])
        _write_store(s)
        return s

    with open(USERFILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    def pick_first(d: dict, keys):
        for k in keys:
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _ensure_user(u: dict) -> User:
        now = _now()
        name = (
            pick_first(u, ["name", "username", "user", "teamName", "displayName"])
            or "noname"
        )
        path = (
            pick_first(
                u,
                [
                    "path",
                    "algorithmPath",
                    "algo",
                    "repo",
                    "repo_path",
                    "dest_path",
                    "dir",
                    "directory",
                    "algo_dir",
                ],
            )
            or ""
        )
        uid = os.path.basename(os.path.normpath(path))
        created = u.get("createdAt") or now
        updated = u.get("updatedAt") or now
        return User(id=uid, name=name, path=path, createdAt=created, updatedAt=updated)

    if isinstance(raw, list):
        users = [_ensure_user(u) for u in raw if isinstance(u, dict)]
        store = UserStore(version=1, updatedAt=_now(), users=users)
        _write_store(store)
        return store

    if isinstance(raw, dict):
        if isinstance(raw.get("users"), list):
            users = [_ensure_user(u) for u in raw["users"] if isinstance(u, dict)]
            version = raw.get("version", 1)
            updated = raw.get("updatedAt", _now())
            store = UserStore(version=version, updatedAt=updated, users=users)
            # 不完全なら整形して保存
            if (
                "version" not in raw
                or "updatedAt" not in raw
                or any(
                    not isinstance(u, dict) or "name" not in u or "path" not in u
                    for u in raw["users"]
                )
            ):
                _write_store(store)
            return store
        else:
            user = _ensure_user(raw)
            store = UserStore(version=1, updatedAt=_now(), users=[user])
            _write_store(store)
            return store

    # それでも想定外 → 空に修復
    s = UserStore(version=1, updatedAt=_now(), users=[])
    _write_store(s)
    return s


@app.get("/users", response_model=List[User])
def list_users():
    return _read_store().users


class CreateUserIn(BaseModel):
    name: str
    path: str


def _canon_path(p: str) -> str:
    """ざっくり正規化（末尾スラなし・バックスラ→スラ）。空は空で返す。"""
    s = (p or "").strip().replace("\\", "/")
    if not s:
        return ""
    return os.path.normpath(s)


@app.post("/users", response_model=User)
def create_user(body: CreateUserIn, response: Response):
    # 読み込み（耐性版 _read_store が入ってる前提）
    try:
        store = _read_store()
    except Exception as e:
        logger.exception("read_store failed")
        raise HTTPException(500, f"read_store failed: {e}")

    name = (body.name or "").strip()
    path = _canon_path(body.path)
    if not name or not path:  # ← 空は _canon_path で "" のままになる
        raise HTTPException(400, "name and path required")
    now = _now()

    # 1) path 一致を最優先でアップサート
    for i, u in enumerate(store.users):
        upath = _canon_path(
            getattr(u, "path", u.get("path") if isinstance(u, dict) else "")
        )
        if upath == path:
            data = _to_dict(u)
            data["name"] = name or data.get("name") or "noname"
            data["path"] = path
            data["updatedAt"] = now
            store.users[i] = User(**data)
            try:
                _write_store(store)
            except Exception as e:
                logger.exception("write_store failed")
                raise HTTPException(500, f"write_store failed: {e}")
            response.status_code = status.HTTP_200_OK
            return store.users[i]

    # 2) name 一致でもアップサート（path を最新に）
    for i, u in enumerate(store.users):
        uname = getattr(u, "name", u.get("name") if isinstance(u, dict) else "")
        if (uname or "").strip() == name:
            data = _to_dict(u)
            data["path"] = path
            data["updatedAt"] = now
            store.users[i] = User(**data)
            try:
                _write_store(store)
            except Exception as e:
                logger.exception("write_store failed")
                raise HTTPException(500, f"write_store failed: {e}")
            response.status_code = status.HTTP_200_OK
            return store.users[i]

    # 3) どちらも無ければ新規作成
    u = User(
        id=f"usr_{os.urandom(6).hex()}",
        name=name,
        path=path,
        createdAt=now,
        updatedAt=now,
    )
    store.users.append(u)
    try:
        _write_store(store)
    except Exception as e:
        logger.exception("write_store failed")
        raise HTTPException(500, f"write_store failed: {e}")
    response.status_code = status.HTTP_201_CREATED
    return u


class PatchUserIn(BaseModel):
    # ★ Python 3.9 対応: Optional[str] を使用
    name: Optional[str] = None
    path: Optional[str] = None


@app.patch("/users/{user_id}", response_model=User)
def patch_user(user_id: str, body: PatchUserIn):
    store = _read_store()
    for i, u in enumerate(store.users):
        if u.id == user_id:
            data = _to_dict(u)
            if body.name is not None:
                data["name"] = body.name.strip()
            if body.path is not None:
                data["path"] = body.path.strip()
            data["updatedAt"] = _now()
            store.users[i] = User(**data)
            _write_store(store)
            return store.users[i]
    from fastapi import HTTPException

    raise HTTPException(404, "not found")


@app.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str):
    store = _read_store()
    new_users = [u for u in store.users if u.id != user_id]
    if len(new_users) == len(store.users):
        from fastapi import HTTPException

        raise HTTPException(404, "not found")
    store.users = new_users
    _write_store(store)


def _write_store(store: UserStore):
    with FileLock(USERLOCK, timeout=5):
        store.updatedAt = _now()
        data = json.dumps(_to_dict(store), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(USERFILE))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                fp.write(data)
            os.replace(tmp, USERFILE)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
