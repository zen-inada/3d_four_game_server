from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os, shutil, subprocess
from urllib.parse import urlparse

router = APIRouter()

class CloneRequest(BaseModel):
    repo_url: str

def _owner_repo_from_url(repo_url: str) -> tuple[str, str]:
    path = urlparse(repo_url).path.strip("/")       # e.g. "zen-inada/test-chappy-repo.git"
    parts = path.split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="GitHub URL の形式が不正です")
    owner = parts[0]
    repo  = os.path.splitext(parts[1])[0]
    return owner, repo

def _is_git_repo(path: str) -> bool:
    return os.path.isdir(os.path.join(path, ".git"))

def _run_in_repo(dest_path: str, *args: str):
    # 環境によって対話プロンプトが出ないように
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(args, check=True, cwd=dest_path, env=env)

def _update_existing_repo(dest_path: str):
    # 既存フォルダを Git で最新化（ブランチ自動推測つき）
    _run_in_repo(dest_path, "git", "fetch", "--all", "-p")

    p = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
        cwd=dest_path, capture_output=True, text=True
    )
    if p.returncode == 0 and p.stdout.strip().startswith("origin/"):
        default_branch = p.stdout.strip().split("/", 1)[1]  # "main" など
    else:
        default_branch = "main"

    try:
        _run_in_repo(dest_path, "git", "checkout", "-f", default_branch)
    except subprocess.CalledProcessError:
        _run_in_repo(dest_path, "git", "checkout", "-f", "master")
        default_branch = "master"

    _run_in_repo(dest_path, "git", "reset", "--hard", f"origin/{default_branch}")
    _run_in_repo(dest_path, "git", "clean", "-fdx")  # 生成物や不要ファイルを掃除

@router.post("/clone")
async def clone_repo(req: CloneRequest):
    repo_url = req.repo_url.strip()
    if not repo_url.endswith(".git"):
        raise HTTPException(status_code=400, detail="URLが .git で終わっていません")

    base_dir = "/home/ec2-user/project_3d_four_game/clone_algo/"
    os.makedirs(base_dir, exist_ok=True)

    owner, repo = _owner_repo_from_url(repo_url)
    folder_name = f"{owner}--{repo}"  # 例: zen-inada--test-chappy-repo
    dest_path = os.path.join(base_dir, folder_name)

    # 既存の場合は「中身を最新化」 or 「壊れてたら削除→クリーンクローン」
    if os.path.exists(dest_path):
        if _is_git_repo(dest_path):
            try:
                _update_existing_repo(dest_path)
                return {"message": "♻️ 既存リポジトリを最新化しました", "path": dest_path}
            except subprocess.CalledProcessError:
                shutil.rmtree(dest_path, ignore_errors=True)
        else:
            shutil.rmtree(dest_path, ignore_errors=True)

    # 新規クローン（必要なら浅いクローンにしてもOK: "--depth", "1" を追加）
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        subprocess.run(["git", "clone", repo_url, dest_path], check=True, env=env)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Git clone failed: {e}")

    return {"message": "✅ クローン完了", "path": dest_path}