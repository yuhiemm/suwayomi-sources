from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional


class GithubBuilder:
    """把生成的扩展源码提交到 GitHub，用 Actions 编译。"""

    def __init__(self, repo: str = "yuhiemm/suwayomi-sources", branch: str = "main") -> None:
        self.repo = repo
        self.branch = branch

    def ensure_repo(self, workdir: Path) -> dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        git_dir = workdir / ".git"
        if not git_dir.exists():
            # 尝试 clone；没有则 init + remote
            r = subprocess.run(
                ["gh", "repo", "view", self.repo, "--json", "url", "-q", ".url"],
                capture_output=True,
                text=True,
            )
            if r.returncode == 0:
                url = r.stdout.strip()
                subprocess.run(["git", "clone", url, str(workdir)], check=True)
            else:
                subprocess.run(["gh", "repo", "create", self.repo, "--private", "--confirm"], check=False)
                subprocess.run(["git", "init"], cwd=workdir, check=True)
                subprocess.run(["git", "branch", "-M", self.branch], cwd=workdir, check=True)
                subprocess.run(["gh", "repo", "sync", self.repo], cwd=workdir, check=False)
                # remote
                subprocess.run(
                    ["git", "remote", "add", "origin", f"git@github.com:{self.repo}.git"],
                    cwd=workdir,
                    check=False,
                )
        self._ensure_workflow(workdir)
        return {"repo": self.repo, "workdir": str(workdir)}

    def _ensure_workflow(self, workdir: Path) -> None:
        wf = workdir / ".github" / "workflows" / "build-extension.yml"
        wf.parent.mkdir(parents=True, exist_ok=True)
        if wf.exists():
            return
        wf.write_text(
            """name: build-extension
on:
  push:
    paths:
      - 'src/**'
      - '.github/workflows/build-extension.yml'
  workflow_dispatch:
    inputs:
      module:
        description: 'extension module path under src/'
        required: false
        default: ''

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'
      - name: Setup Android SDK
        uses: android-actions/setup-android@v3
      - name: Build
        run: |
          if [ -f gradlew ]; then
            chmod +x gradlew
            ./gradlew assembleDebug --stacktrace || true
          else
            echo "No gradle wrapper yet; upload source only"
          fi
          mkdir -p dist
          find . -name '*.jar' -o -name '*.apk' | head
          find . -name 'tachiyomi-*.jar' -exec cp {} dist/ \\; || true
          find . -path '*/build/outputs/apk/debug/*.apk' -exec cp {} dist/ \\; || true
      - uses: actions/upload-artifact@v4
        with:
          name: extensions
          path: dist/
          if-no-files-found: warn
""",
            encoding="utf-8",
        )

    def publish_extension(self, workdir: Path, extension_dir: Path, message: str = "") -> dict[str, Any]:
        self.ensure_repo(workdir)
        dest = workdir / "src" / extension_dir.name
        if dest.exists():
            subprocess.run(["rm", "-rf", str(dest)], check=True)
        subprocess.run(["cp", "-a", str(extension_dir), str(dest)], check=True)
        subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
        msg = message or f"feat: add extension {extension_dir.name}"
        # 中文提交
        commit = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=workdir,
            capture_output=True,
            text=True,
        )
        push = subprocess.run(
            ["git", "push", "-u", "origin", self.branch],
            cwd=workdir,
            capture_output=True,
            text=True,
        )
        return {
            "ok": push.returncode == 0,
            "commit_out": commit.stdout + commit.stderr,
            "push_out": push.stdout + push.stderr,
            "path": str(dest),
            "repo": self.repo,
        }

    def download_latest_artifact(self, out_dir: Path) -> Optional[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        # gh run download
        r = subprocess.run(
            ["gh", "run", "list", "--repo", self.repo, "--limit", "1", "--json", "databaseId,status,conclusion"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return None
        runs = json.loads(r.stdout or "[]")
        if not runs:
            return None
        run_id = str(runs[0]["databaseId"])
        d = out_dir / f"run-{run_id}"
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["gh", "run", "download", run_id, "--repo", self.repo, "-D", str(d)],
            check=False,
        )
        jars = list(d.rglob("*.jar")) + list(d.rglob("*.apk"))
        return jars[0] if jars else None
