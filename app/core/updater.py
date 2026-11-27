"""GitHub auto-updater for GLCSS (supports both git-clone and zip-installed deployments)."""

from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from app.config import APP_ROOT

GITHUB_REPO = "Chars1008/lcss-lab-safety"
GITHUB_API_COMMIT = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip"


@dataclass
class UpdateCheckResult:
    has_update: bool
    local_sha: str
    remote_sha: str
    message: str


class GitHubUpdater:
    """Checks for updates on GitHub and applies updates safely without overwriting user data."""

    def __init__(self, app_root: Optional[Path] = None, timeout: float = 30.0) -> None:
        self.app_root = app_root or APP_ROOT
        self.timeout = timeout
        self.version_file = self.app_root / "config" / "version.txt"

    def get_local_sha(self) -> str:
        git_dir = self.app_root / ".git"
        if git_dir.exists():
            try:
                res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(self.app_root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if res.returncode == 0:
                    return res.stdout.strip()[:7]
            except Exception:
                pass
        if self.version_file.exists():
            return self.version_file.read_text(encoding="utf-8").strip()[:7]
        return "unknown"

    def get_remote_sha(self, client: Optional[httpx.Client] = None) -> str:
        own = client is None
        http = client or httpx.Client(timeout=self.timeout, follow_redirects=True)
        try:
            resp = http.get(GITHUB_API_COMMIT, headers={"Accept": "application/vnd.github.v3+json"})
            if resp.status_code != 200:
                raise RuntimeError(f"GitHub API HTTP {resp.status_code}")
            sha = resp.json().get("sha", "")
            return sha[:7]
        finally:
            if own:
                http.close()

    def check_for_updates(self, client: Optional[httpx.Client] = None) -> UpdateCheckResult:
        local_sha = self.get_local_sha()
        try:
            remote_sha = self.get_remote_sha(client=client)
        except Exception as exc:
            return UpdateCheckResult(False, local_sha, "", f"無法連線至 GitHub：{exc}")

        if not remote_sha:
            return UpdateCheckResult(False, local_sha, "", "無法取得遠端版本資訊。")
        if local_sha == remote_sha:
            return UpdateCheckResult(False, local_sha, remote_sha, f"目前已是最新版本 ({local_sha})。")
        return UpdateCheckResult(
            True,
            local_sha,
            remote_sha,
            f"發現新版本：{remote_sha}（目前版本：{local_sha}）",
        )

    def apply_update(self, client: Optional[httpx.Client] = None) -> tuple[bool, str]:
        """Apply update from GitHub main branch while preserving config/ and storage/."""
        git_dir = self.app_root / ".git"
        if git_dir.exists():
            try:
                res = subprocess.run(
                    ["git", "pull", "--ff-only", "origin", "main"],
                    cwd=str(self.app_root),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if res.returncode == 0:
                    new_sha = self.get_local_sha()
                    return True, f"已透過 Git 更新至最新版本 ({new_sha})，請重新啟動程式以套用。"
                return False, f"Git 更新失敗：{res.stderr.strip() or res.stdout.strip()}"
            except Exception as exc:
                return False, f"Git 更新發生錯誤：{exc}"

        # Non-git installed mode: download main.zip and overlay app/, data/, installer/, main.py, pyproject.toml
        own = client is None
        http = client or httpx.Client(timeout=max(self.timeout, 60.0), follow_redirects=True)
        try:
            remote_sha = self.get_remote_sha(client=http)
            resp = http.get(GITHUB_ZIP_URL)
            if resp.status_code != 200:
                return False, f"下載更新包失敗：HTTP {resp.status_code}"

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                names = zf.namelist()
                if not names:
                    return False, "更新壓縮檔為空。"
                top_prefix = names[0].split("/")[0] + "/"
                allowed_prefixes = ("app/", "data/", "installer/", "main.py", "pyproject.toml", "README.md")
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    if not member.filename.startswith(top_prefix):
                        continue
                    rel = member.filename[len(top_prefix):]
                    if not rel.startswith(allowed_prefixes):
                        continue
                    target = self.app_root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src_f, target.open("wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)

            if remote_sha:
                self.version_file.parent.mkdir(parents=True, exist_ok=True)
                self.version_file.write_text(remote_sha, encoding="utf-8")
            return True, f"已從 GitHub 下載更新至版本 {remote_sha or 'latest'}，請重新啟動程式以套用。"
        except Exception as exc:
            return False, f"線上更新失敗：{exc}"
        finally:
            if own:
                http.close()
