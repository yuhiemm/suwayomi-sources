# suwayomi-ext-agent

输入漫画网站 URL → **Agent 自动解析站点结构** → 生成 Suwayomi/Tachiyomi 扩展源码 → 推送 GitHub 编译 → 导入本机 Suwayomi。

> 每个网站 DOM/API 都不一样，所以不做写死源，而是 **先分析再生成**。

## 流程

```
URL
 ├─ 1. 代理核验（yuhiemm pool / WARP，禁止直连）
 ├─ 2. 探测首页/热门/最新/搜索路径
 ├─ 3. 推断列表/详情/章节/图片选择器或 API
 ├─ 4. 输出 SiteStructure + confidence
 ├─ 5. 生成 Kotlin ParsedHttpSource 骨架
 ├─ 6. 推 GitHub Actions 编译
 └─ 7. 安装 JAR 到 Suwayomi
```

## 代理策略

| 模式 | 说明 |
|------|------|
| `pool`（默认） | yuhiemm 代理池，`platform=speed` |
| `warp` | 本机 WARP `10.0.0.39:1080` |
| `home` | **禁用** |

密钥：`/home/ubuntu/.hermes/secrets/yuhiemm-proxy-pool.env`（不入库、不打印密码）

## 使用

```bash
cd /home/ubuntu/suwayomi-ext-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 核验代理出口
python -m agent check

# 只分析结构
python -m agent analyze https://example-manga.com --name "示例"

# 分析 + 生成源码
python -m agent generate https://example-manga.com --name "示例"

# 分析 + 生成 + 推 GitHub（可加 --install）
python -m agent build https://example-manga.com --name "示例"

# 换 WARP
python -m agent --proxy-mode warp analyze https://example-manga.com
```

## 目录

```
agent/
  proxy.py          # 代理池 URL 构造
  warp_client.py    # CrawlClient（强制代理）
  analyzer.py       # 站点结构分析（核心）
  generator.py      # 扩展源码生成
  github_builder.py # GitHub 推送/产物
  installer.py      # 导入 Suwayomi
  __main__.py       # CLI
```
