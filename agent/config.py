from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = {
    # 爬取代理：默认走 yuhiemm 代理池 speed，禁止直连
    "proxy_mode": "pool",  # pool | warp
    "proxy_platform": "speed",  # all/speed/regis （home 禁用）
    "proxy_scheme": "socks5h",
    "proxy_route_user": "",
    "proxy_url": "",
    "warp_proxy": "socks5h://10.0.0.39:1080",
    "force_proxy": True,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "timeout": 30,
    "flaresolverr_url": "http://127.0.0.1:8191",
    "suwayomi_url": "http://127.0.0.1:4567",
    "suwayomi_user": "",
    "suwayomi_pass": "",
    "suwayomi_extensions_dir": "/home/ubuntu/suwayomi/data/extensions",
    "github_repo": "yuhiemm/suwayomi-sources",
    "github_branch": "main",
    "output_dir": str(ROOT / "output"),
    "lang": "zh",
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    conf_path = Path(path) if path else ROOT / "config.yaml"
    if conf_path.exists():
        with conf_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if v is not None})

    env_map = {
        "PROXY_MODE": "proxy_mode",
        "PROXY_PLATFORM": "proxy_platform",
        "PROXY_SCHEME": "proxy_scheme",
        "PROXY_ROUTE_USER": "proxy_route_user",
        "PROXY_URL": "proxy_url",
        "WARP_PROXY": "warp_proxy",
        "FORCE_PROXY": "force_proxy",
        "FORCE_WARP": "force_proxy",
        "FLARESOLVERR_URL": "flaresolverr_url",
        "SUWAYOMI_URL": "suwayomi_url",
        "SUWAYOMI_USER": "suwayomi_user",
        "SUWAYOMI_PASS": "suwayomi_pass",
        "SUWAYOMI_EXTENSIONS_DIR": "suwayomi_extensions_dir",
        "GITHUB_REPO": "github_repo",
        "GITHUB_BRANCH": "github_branch",
    }
    for env_key, cfg_key in env_map.items():
        val = os.getenv(env_key)
        if val is None or val == "":
            continue
        if cfg_key == "force_proxy":
            cfg[cfg_key] = val.lower() in {"1", "true", "yes", "on"}
        else:
            cfg[cfg_key] = val
    # 兼容旧字段
    if "force_warp" in cfg and "force_proxy" not in cfg:
        cfg["force_proxy"] = cfg["force_warp"]
    return cfg
