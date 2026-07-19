from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import httpx


class SuwayomiInstaller:
    """把扩展 JAR 安装进本机 Suwayomi。

    优先走 HTTP API；失败则直接复制到 extensions 目录并重启容器。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4567",
        username: str = "",
        password: str = "",
        extensions_dir: str = "/home/ubuntu/suwayomi/data/extensions",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.extensions_dir = Path(extensions_dir)
        self.auth = (username, password) if username else None

    def install_jar(self, jar_path: str | Path, restart: bool = True) -> dict[str, Any]:
        jar = Path(jar_path)
        if not jar.exists():
            raise FileNotFoundError(jar)

        # 1) 尝试 REST 上传
        api_result = self._try_api_install(jar)
        if api_result.get("ok"):
            return api_result

        # 2) 直接落盘
        self.extensions_dir.mkdir(parents=True, exist_ok=True)
        dest = self.extensions_dir / jar.name
        # 目录属主可能是 opc/suwayomi
        try:
            shutil.copy2(jar, dest)
        except PermissionError:
            subprocess.run(["sudo", "cp", str(jar), str(dest)], check=True)
            subprocess.run(["sudo", "chown", "opc:opc", str(dest)], check=False)

        restarted = False
        if restart:
            restarted = self._restart_suwayomi()
        return {
            "ok": True,
            "method": "filesystem",
            "dest": str(dest),
            "api_error": api_result.get("error"),
            "restarted": restarted,
        }

    def _try_api_install(self, jar: Path) -> dict[str, Any]:
        # Suwayomi 不同版本 endpoint 可能不同，逐个尝试
        endpoints = [
            "/api/v1/extension/install",
            "/api/v1/extension/install/0",
        ]
        data = jar.read_bytes()
        with httpx.Client(base_url=self.base_url, auth=self.auth, timeout=60.0) as client:
            for ep in endpoints:
                try:
                    files = {"file": (jar.name, data, "application/java-archive")}
                    r = client.post(ep, files=files)
                    if r.status_code < 400:
                        return {"ok": True, "method": f"api:{ep}", "status": r.status_code, "body": r.text[:300]}
                except Exception as e:
                    last = str(e)
                else:
                    last = f"HTTP {r.status_code}: {r.text[:200]}"
            # GraphQL mutation 尝试（部分版本支持）
            try:
                b64 = base64.b64encode(data).decode()
                query = {
                    "query": "mutation($file: String!){ installExternalExtension(extensionFile: $file){ extension { name pkgName } } }",
                    "variables": {"file": b64},
                }
                r = client.post("/api/graphql", json=query)
                if r.status_code < 400 and "errors" not in r.text:
                    return {"ok": True, "method": "graphql", "status": r.status_code, "body": r.text[:300]}
                last = f"graphql HTTP {r.status_code}: {r.text[:200]}"
            except Exception as e:
                last = str(e)
        return {"ok": False, "error": last}

    def _restart_suwayomi(self) -> bool:
        try:
            subprocess.run(
                ["sudo", "docker", "restart", "suwayomi-server"],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return True
        except Exception:
            return False

    def list_local_jars(self) -> list[str]:
        if not self.extensions_dir.exists():
            return []
        return sorted(p.name for p in self.extensions_dir.glob("*.jar"))
