---
name: tiktok-photo-publisher
version: "1.0"
description: TikTok 图文发布器 — 将产品图片转为轮播视频，通过 AdsPower 指纹浏览器自动发布到多个 TikTok 账号。支持多账号批量发布、住宅代理、自动降级和人工兜底。
tags: [tiktok, social-media, publishing, automation, browser-automation, ffmpeg, adspower]
---

# TikTok 图文发布器 v1.0

将产品推荐图片自动发布到 TikTok，为外贸店铺引流。

## 核心能力

- **图片→视频转换**: FFmpeg 将多张图片生成 1080x1920 竖屏轮播视频（带渐变过渡）
- **AdsPower 指纹浏览器**: 每个账号独立浏览器指纹 + 住宅代理 IP
- **Selenium 自动化**: 自动上传视频、填写描述、点击发布
- **多账号批量**: ThreadPoolExecutor 并发 + 账号间延迟防风控
- **双轨发布**: API 模式（待开发者审批）+ 浏览器模式（当前可用）
- **人工兜底**: 自动化失败时生成 handoff JSON 包含操作步骤和截图

## 使用场景

- 外贸业务批量发布产品图文到多个 TikTok 账号
- 用户说 "发布到 TikTok"、"批量发图"、"TikTok 图文"
- 需要管理多个 TikTok 账号的发布任务

## 架构

```
scripts/publish.py          (CLI 入口)
  → src/publisher.py        (双轨调度: API / 浏览器)
    → src/publisher_api.py  (TikTok Content Posting API)
    → src/publisher_browser.py (AdsPower + Selenium)
      → src/video_maker.py  (FFmpeg 图片→视频)
      → src/adspower.py     (AdsPower 本地 API)
  → src/batch.py            (多账号并发编排)
  → src/accounts.py         (账号管理)
  → src/oauth.py            (OAuth 2.0 + PKCE)
  → src/cdn.py              (Cloudflare R2 图片 CDN)
```

## 前置依赖

- Python 3.12+
- FFmpeg (PATH 中可用)
- AdsPower 指纹浏览器 (已安装并登录)
- 住宅代理 (NodeMaven 或其他)

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置账号 (参考 config/accounts.example.json)
cp config/accounts.example.json config/accounts.json

# 单账号发布
python scripts/publish.py \
  --account tiktok_sa_02 \
  --title "Spring Collection 2026" \
  --description "Shop now! #fashion" \
  --images photos/1.jpg photos/2.jpg photos/3.jpg

# 批量发布到所有活跃账号
python scripts/publish.py \
  --all-active \
  --title "New Arrivals" \
  --images photos/*.jpg

# 试运行 (不实际发布)
python scripts/publish.py --account tiktok_sa_02 --dry-run \
  --title "Test" --images test.jpg
```

## 关键经验

1. **TikTok 网页版不支持图文上传** — 只能上传视频，所以图片必须先转为轮播视频
2. **AdsPower 创建 profile 后必须用 update API 确认代理** — create 时的 proxy 可能被忽略
3. **TikTok 对住宅代理 IP 段敏感** — NodeMaven 沙特 IP 被封，需测试可用性
4. **白号封号率约 37%** — 建议购买满月号或千粉号
5. **环境变量优先于 JSON 配置** — 凭据通过 `TIKTOK_CLIENT_KEY`、`R2_*`、`PROXY_*` 环境变量传入

## 配置

### 环境变量 (.env)

```bash
# TikTok Developer App (API 模式)
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=

# Cloudflare R2 (API 模式 CDN)
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=social-media-assets
R2_PUBLIC_URL_BASE=
R2_ENDPOINT_URL=

# 代理 (AdsPower profile 创建)
PROXY_HOST=gate.nodemaven.com
PROXY_PORT=8080
PROXY_USER=
PROXY_PASSWORD=
```

### 账号配置 (config/accounts.json)

```json
{
  "accounts": [
    {
      "account_id": "tiktok_sa_02",
      "display_name": "SA Store 02",
      "tiktok_username": "user...",
      "status": "active",
      "auth_mode": "browser",
      "adspower_profile_id": "k1b2t42a",
      "region": "沙特",
      "tags": ["store", "saudi"],
      "defaults": {
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "disable_comment": false
      }
    }
  ]
}
```

## 版本历史

### v1.0 (2026-04-02)
- 初始版本
- 图片→视频轮播 (FFmpeg xfade)
- AdsPower + Selenium 浏览器自动化
- 多账号批量发布
- 双轨调度 (API + 浏览器)
- 三方代码审核修复 (Codex + code-reviewer + architect)
