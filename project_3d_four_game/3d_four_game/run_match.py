# run_match.py
import requests # type: ignore
import time

BASE = "http://35.74.10.149:8000"
# 例: 先手が ai2 の場合は入れ替える
first = "ai1"  # ← コマンドライン引数や設定で指定できるようにする
players = {1: "player1", 2: "player2"} if first == "ai1" else {1: "player2", 2: "player1"}

def get_board():
    r = requests.get(f"{BASE}/board")
    r.raise_for_status()
    return r.json()

def make_move(x, y):
    r = requests.post(f"{BASE}/move", params={"x": x, "y": y})
    r.raise_for_status()
    return r.json()

def ask_algo(player_id, board):
    r = requests.post(f"{BASE}/algo-move", json={"player_id": player_id, "board": board})
    r.raise_for_status()
    return r.json()["move"]

def reset():
    requests.post(f"{BASE}/reset")

def run_match():
    reset()
    while True:
        state = get_board()
        if state["game_over"]:
            print("✅ Game Over:", state)
            break

        board = state["board"]
        current_player = state["current_player"]
        player_id = players[current_player]

        # アルゴで手を取得
        move = ask_algo(player_id, board)
        x, y = move["x"], move["y"]
        print(f"🧠 Player {current_player}({player_id}) → x={x}, y={y}")

        # 盤へ反映
        result = make_move(x, y)
        if result["status"] in ["win", "draw", "finished"]:
            print("🎉 終了:", result)
            break

        time.sleep(0.05)  # ログ見やすく

if __name__ == "__main__":
    run_match()
