import importlib.util, json, sys, os, resource, traceback, pathlib
import io, contextlib, ast, sysconfig, builtins


def set_limits(max_mem_mb="1024", cpu_time_sec="3"):
    try:
        resource.setrlimit(resource.RLIMIT_AS, (int(max_mem_mb) * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_time_sec),) * 2)
    except Exception:
        pass  # 環境によって未対応でもOK


# === セキュリティ設定 ===
_BANNED_IMPORTS = {
    "importlib",
    "os",
    "sys",
    "subprocess",
    "socket",
    "pathlib",
    "shutil",
    "glob",
    "requests",
    "urllib",
    "urllib3",
    "http",
    "ssl",
    "ftplib",
    "aiohttp",
    "ctypes",
    "multiprocessing",
    "threading",
    "concurrent",
    "asyncio",
}
_BANNED_CALLS = {"open", "eval", "exec", "compile", "__import__", "system", "popen"}


def _ast_gate(source_code: str, filename: str):
    """提出ファイルの AST を見て危険な import/call を拒否"""
    tree = ast.parse(source_code, filename=filename)

    class Guard(ast.NodeVisitor):
        def visit_Import(self, node):
            for n in node.names:
                base = (n.name or "").split(".")[0]
                if base in _BANNED_IMPORTS:
                    raise RuntimeError(f"banned import: {n.name}")

        def visit_ImportFrom(self, node):
            base = (node.module or "").split(".")[0]
            if base in _BANNED_IMPORTS:
                raise RuntimeError(f"banned import: {node.module}")

        def visit_Call(self, node):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in _BANNED_CALLS:
                raise RuntimeError(f"banned call: {name}")
            self.generic_visit(node)

    Guard().visit(tree)


def _install_runtime_guards():
    """ランタイムで危険 import と一部ビルトインを封じる。
    ※ compile は無効化しない（import 実装で必要になるため）
    """
    orig_import = builtins.__import__

    def secure_import(name, globals=None, locals=None, fromlist=(), level=0):
        base = (name or "").split(".")[0]
        if base in _BANNED_IMPORTS:
            raise RuntimeError(f"banned import at runtime: {name}")
        return orig_import(name, globals, locals, fromlist, level)

    builtins.__import__ = secure_import

    # ファイル I/O と eval を封じる（モジュール“読込後”に呼ぶこと）
    def _deny(*a, **kw):
        raise RuntimeError("this builtin is disabled")

    if hasattr(builtins, "open"):
        builtins.open = _deny  # type: ignore
    if hasattr(builtins, "eval"):
        builtins.eval = _deny  # type: ignore
    # compile は触らない


def load_module(path: str):
    # 事前 AST チェック
    src = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    _ast_gate(src, str(path))

    spec = importlib.util.spec_from_file_location("algo_worker_mod", path)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load module from {path}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_module(path: str):
    # 事前 AST チェック
    src = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    _ast_gate(src, str(path))

    spec = importlib.util.spec_from_file_location("algo_worker_mod", path)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load module from {path}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "no algo_path"}))
        return 2

    algo_path = sys.argv[1]
    algo_dir = str(pathlib.Path(algo_path).resolve().parent)

    # === sys.path をホワイトリスト化：提出フォルダ＋標準ライブラリ(+lib-dynload)+framework ===
    paths = sysconfig.get_paths()
    stdlib = paths.get("stdlib")
    platstdlib = paths.get("platstdlib")
    allow = [algo_dir]

    for p in (stdlib, platstdlib):
        if p and p not in allow:
            allow.append(p)
        if p:
            dyn = os.path.join(p, "lib-dynload")
            if os.path.isdir(dyn) and dyn not in allow:
                allow.append(dyn)

    # ★ framework.py を置いたディレクトリを追加
    allow.append("/home/ec2-user/project_3d_four_game_verify/3d_four_game")

    sys.path[:] = allow

    set_limits(
        os.environ.get("WORKER_MAX_MEM_MB", "1024"),
        os.environ.get("WORKER_CPU_TIME", "3"),
    )

    try:
        # stdin は一度だけ読む
        board = json.loads(sys.stdin.read())

        # まず AST ゲート付きでロード
        m = load_module(algo_path)

        # --- get_move または MyAI を探す ---
        func = None
        if hasattr(m, "get_move") and callable(m.get_move):
            func = m.get_move
        elif hasattr(m, "MyAI"):
            _ai = m.MyAI()
            if hasattr(_ai, "get_move") and callable(_ai.get_move):
                func = _ai.get_move

        if func is None:
            raise AttributeError(f"{algo_path} に get_move または MyAI が見つかりません")

        # ランタイムガードを有効化
        _install_runtime_guards()

        # ★ アルゴの print は stderr に流す（stdoutは最終JSONのみ）
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            x, y = func(board)

        logs = buf.getvalue()
        if logs:
            print(logs, file=sys.stderr, end="")

        print(json.dumps({"x": int(x), "y": int(y)}))
        return 0

    except Exception as e:
        traceback.print_exc()
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
