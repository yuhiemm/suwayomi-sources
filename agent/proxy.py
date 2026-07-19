from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote


SECRET_FILE = Path("/home/ubuntu/.hermes/secrets/yuhiemm-proxy-pool.env")
VALID_PLATFORMS = ("all", "home", "speed", "regis")


def load_proxy_pool_env(path: Path = SECRET_FILE) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_proxy_url(
    platform: str = "speed",
    scheme: str = "socks5h",
    route_user: str = "",
    env: Optional[dict[str, str]] = None,
) -> str:
    """构造代理 URL。默认 speed；不要打印返回值中的密码。"""
    data = env or load_proxy_pool_env()
    host = data.get("YUHIEMM_PROXY_POOL_HOST", "")
    port = data.get("YUHIEMM_PROXY_POOL_PORT", "")
    user = data.get("YUHIEMM_PROXY_POOL_USER", "")
    password = data.get("YUHIEMM_PROXY_POOL_PASSWORD", "")
    if not all([host, port, user, password]):
        raise RuntimeError(f"代理池密钥不完整: {SECRET_FILE}")
    if platform not in VALID_PLATFORMS:
        raise ValueError(f"无效 platform={platform}，可选: {VALID_PLATFORMS}")
    if platform == "home":
        # 用户规则：home 勿用（除非显式强制）
        raise ValueError("platform=home 已禁用，请用 speed/all/regis")
    if route_user:
        auth_user = f"{platform}.{route_user}.{user}"
    else:
        auth_user = f"{platform}.{user}"
    # 密码可能含特殊字符
    return (
        f"{scheme}://{quote(auth_user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    )


def proxy_label(platform: str = "speed", route_user: str = "", scheme: str = "socks5h") -> str:
    """仅用于日志，不含密码。"""
    if route_user:
        return f"{scheme}://{platform}.{route_user}.***@***"
    return f"{scheme}://{platform}.***@***"


def resolve_crawl_proxy(cfg: dict[str, Any]) -> tuple[str, str]:
    """按配置解析爬取代理。

    优先级：
    1) cfg['proxy_url'] 显式指定
    2) proxy_pool (默认 speed)
    3) warp_proxy 兜底
    """
    if cfg.get("proxy_url"):
        return str(cfg["proxy_url"]), "explicit"
    mode = str(cfg.get("proxy_mode") or "pool").lower()
    if mode in {"pool", "proxy_pool", "yuhiemm", "speed", "all", "regis"}:
        platform = str(cfg.get("proxy_platform") or "speed")
        if mode in VALID_PLATFORMS:
            platform = mode
        route = str(cfg.get("proxy_route_user") or "")
        scheme = str(cfg.get("proxy_scheme") or "socks5h")
        url = build_proxy_url(platform=platform, scheme=scheme, route_user=route)
        return url, proxy_label(platform, route, scheme)
    # warp
    warp = str(cfg.get("warp_proxy") or "socks5h://10.0.0.39:1080")
    return warp, "warp:10.0.0.39:1080"
