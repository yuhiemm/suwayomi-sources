from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .analyzer import SiteAnalyzer
from .config import load_config
from .generator import ExtensionGenerator
from .github_builder import GithubBuilder
from .installer import SuwayomiInstaller
from .proxy import resolve_crawl_proxy
from .warp_client import CrawlClient

console = Console()


def _client(cfg: dict) -> CrawlClient:
    proxy, label = resolve_crawl_proxy(cfg)
    return CrawlClient(
        proxy=proxy,
        proxy_label=label,
        user_agent=cfg.get("user_agent", ""),
        timeout=float(cfg.get("timeout", 30)),
        flaresolverr_url=cfg.get("flaresolverr_url", "http://127.0.0.1:8191"),
        force_proxy=bool(cfg.get("force_proxy", True)),
    )


def cmd_check(cfg: dict) -> int:
    with _client(cfg) as client:
        info = client.verify_exit()
    console.print("[bold]代理出口检查[/bold]")
    console.print(info)
    if not info.get("ok"):
        console.print("[red]代理不可用[/red]")
        return 1
    # 再测直连对比（不用于爬源站）
    try:
        import httpx

        direct = httpx.get("https://api.ipify.org", timeout=10).text.strip()
        console.print(f"直连出口(仅对比): {direct}")
        if direct and direct == info.get("ip"):
            console.print("[red]警告: 代理出口与直连相同，可能未走代理[/red]")
            return 2
        console.print("[green]代理出口与直连不同，核验通过[/green]")
    except Exception as e:
        console.print(f"[yellow]直连对比失败: {e}[/yellow]")
    return 0


def cmd_analyze(cfg: dict, url: str, name: str = "", out: str = "") -> int:
    with _client(cfg) as client:
        console.print(f"[cyan]经代理分析站点结构[/cyan]: {url}")
        info = client.verify_exit()
        console.print(f"proxy={info.get('proxy')} ip={info.get('ip')} loc={info.get('loc')}")
        if not info.get("ok"):
            console.print("[red]代理不可用，中止（禁止直连爬源站）[/red]")
            return 1
        analyzer = SiteAnalyzer(client, lang=cfg.get("lang", "zh"))
        structure = analyzer.analyze(url, site_name=name)
    summary = structure.summary()
    table = Table(title="站点结构分析结果")
    table.add_column("字段")
    table.add_column("值")
    for k, v in summary.items():
        table.add_row(k, json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else str(v))
    console.print(table)
    out_path = Path(out or Path(cfg["output_dir"]) / "last_analysis.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(structure.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"完整结果: {out_path}")
    console.print(f"confidence={structure.confidence:.2f}")
    return 0


def cmd_generate(cfg: dict, url: str, name: str = "", pkg: str = "") -> int:
    with _client(cfg) as client:
        console.print(f"[cyan]代理分析 + 生成扩展源码[/cyan]: {url}")
        info = client.verify_exit()
        console.print(info)
        if not info.get("ok"):
            return 1
        structure = SiteAnalyzer(client, lang=cfg.get("lang", "zh")).analyze(url, site_name=name)
    gen = ExtensionGenerator(cfg["output_dir"])
    report = gen.generate(structure, display_name=name or None, pkg=pkg or None)
    console.print_json(data=report)
    console.print(f"[green]源码已生成[/green]: {report['path']}")
    return 0


def cmd_build(cfg: dict, url: str, name: str = "", pkg: str = "", install: bool = False) -> int:
    with _client(cfg) as client:
        console.print(f"[cyan]代理分析[/cyan]: {url}")
        info = client.verify_exit()
        console.print(info)
        if not info.get("ok"):
            return 1
        structure = SiteAnalyzer(client, lang=cfg.get("lang", "zh")).analyze(url, site_name=name)
    gen = ExtensionGenerator(cfg["output_dir"])
    report = gen.generate(structure, display_name=name or None, pkg=pkg or None)
    ext_path = Path(report["path"])
    console.print(f"生成: {ext_path}")

    workdir = Path(cfg["output_dir"]) / "github-repo"
    gb = GithubBuilder(repo=cfg.get("github_repo", "yuhiemm/suwayomi-sources"), branch=cfg.get("github_branch", "main"))
    pub = gb.publish_extension(workdir, ext_path, message=f"feat: 添加扩展 {report['display_name']}")
    console.print({k: v for k, v in pub.items() if k != "push_out" or len(str(v)) < 500})
    if not pub.get("ok"):
        console.print("[yellow]GitHub 推送失败，源码仍在 output/[/yellow]")
        return 2

    if install:
        art = gb.download_latest_artifact(Path(cfg["output_dir"]) / "artifacts")
        if not art:
            console.print("[yellow]暂无 CI 产物。完成后: python -m agent install <jar>[/yellow]")
            return 0
        inst = SuwayomiInstaller(
            base_url=cfg["suwayomi_url"],
            username=cfg.get("suwayomi_user") or "",
            password=cfg.get("suwayomi_pass") or "",
            extensions_dir=cfg["suwayomi_extensions_dir"],
        )
        console.print(inst.install_jar(art))
    return 0


def cmd_install(cfg: dict, jar: str) -> int:
    inst = SuwayomiInstaller(
        base_url=cfg["suwayomi_url"],
        username=cfg.get("suwayomi_user") or "",
        password=cfg.get("suwayomi_pass") or "",
        extensions_dir=cfg["suwayomi_extensions_dir"],
    )
    res = inst.install_jar(jar)
    console.print(res)
    return 0 if res.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="suwayomi-ext-agent",
        description="Agent：解析任意漫画站结构 → 生成 Suwayomi 扩展（爬取走代理池/WARP）",
    )
    parser.add_argument("--config", default="", help="config.yaml 路径")
    parser.add_argument("--proxy-mode", default="", help="pool|warp")
    parser.add_argument("--proxy-platform", default="", help="speed|all|regis")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="检查代理出口（并对比直连）")

    p_an = sub.add_parser("analyze", help="只分析站点结构")
    p_an.add_argument("url")
    p_an.add_argument("--name", default="")
    p_an.add_argument("--out", default="")

    p_gen = sub.add_parser("generate", help="分析 + 生成扩展源码")
    p_gen.add_argument("url")
    p_gen.add_argument("--name", default="")
    p_gen.add_argument("--pkg", default="")

    p_build = sub.add_parser("build", help="分析 + 生成 + 推 GitHub 编译")
    p_build.add_argument("url")
    p_build.add_argument("--name", default="")
    p_build.add_argument("--pkg", default="")
    p_build.add_argument("--install", action="store_true")

    p_ins = sub.add_parser("install", help="安装本地 jar 到 Suwayomi")
    p_ins.add_argument("jar")

    args = parser.parse_args(argv)
    cfg = load_config(args.config or None)
    if args.proxy_mode:
        cfg["proxy_mode"] = args.proxy_mode
    if args.proxy_platform:
        cfg["proxy_platform"] = args.proxy_platform

    if args.cmd == "check":
        return cmd_check(cfg)
    if args.cmd == "analyze":
        return cmd_analyze(cfg, args.url, args.name, args.out)
    if args.cmd == "generate":
        return cmd_generate(cfg, args.url, args.name, args.pkg)
    if args.cmd == "build":
        return cmd_build(cfg, args.url, args.name, args.pkg, args.install)
    if args.cmd == "install":
        return cmd_install(cfg, args.jar)
    return 1


if __name__ == "__main__":
    sys.exit(main())
