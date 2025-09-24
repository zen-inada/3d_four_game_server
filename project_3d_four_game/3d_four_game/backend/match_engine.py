import json, subprocess, sys, time


def interact_with_algo(script_path: str, board):
    # 子プロセスは必ず -u（アンバッファ）で起動。text=True で文字列I/O。
    proc = subprocess.Popen(
        [sys.executable, "-u", script_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,               # ← 文字列で扱う
        encoding="utf-8",
        bufsize=1,               # 行バッファ
        universal_newlines=True  # 改行統一
    )

    # 1) 最初の1行を受け取り、余計な空白/改行を除去して照合
    try:
        line = proc.stdout.readline()  # ブロッキングで1行読み
    except Exception:
        # すぐに落ちた等の保険
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"algo failed before handshake: {err}")

    if line is None:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"no output from algo (handshake). stderr:\n{err}")

    if line.strip().lower() != "send_board":   # ← ここ重要（strip/小文字化）
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"期待される 'send_board' が出力されませんでした。受信='{line.rstrip()}' stderr:\n{err}")

    # 2) 盤面を1行JSONで渡す
    payload = json.dumps(board)
    proc.stdin.write(payload + "\n")
    proc.stdin.flush()

    # 3) 応答（x,y）を1行でもらう
    move_line = proc.stdout.readline()
    if move_line is None:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"algo did not return a move. stderr:\n{err}")

    move_line = move_line.strip()
    # "x,y" を想定
    if "," not in move_line:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"invalid move format: '{move_line}'. stderr:\n{err}")

    xs, ys = move_line.split(",", 1)
    x, y = int(xs), int(ys)

    try:
        proc.kill()
    except Exception:
        pass

    return x, y
