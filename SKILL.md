---
name: tiktok-photo-publisher
version: "2.0"
description: TikTok 图文发布器 — Firecrawl 抓取多角度产品图 → RAQM 阿拉伯语品牌模板 → Ken Burns 视频 + BGM → AdsPower 自动发布 + 验证 → Notion 记录 + G 盘归档。支持 5 账号定时发布、9 品类轮换、Gulf 市场双语内容。
tags: [tiktok, social-media, publishing, automation, browser-automation, ffmpeg, adspower, gulf-market, arabic]
---

# TikTok 图文发布器 v2.0

Gulf 市场（沙特/阿联酋）产品推荐图文自动发布系统。

## 核心能力

- **Firecrawl 抓图**: IKEA SA 多角度产品图抓取，质量筛选（分辨率/色彩方差/去白底），场景图优先排序
- **品牌模板**: RAQM 阿拉伯语渲染 + 模糊背景 + 品牌栏 + ⭐ ترشيح مميز badge + 双语文字
- **Ken Burns 视频**: zoom-in/pan-left 交替 + 4 种过渡效果 + 免版权 BGM + CRF 18 高画质
- **长文案生成**: Gulf 方言阿拉伯语 8-10 行影响者风格 + 英文推荐 + 随机 hashtag 组合
- **发布验证**: Post 后导航 profile 对比视频数，失败自动重试一次
- **5 账号矩阵**: 厨房/家居/浴室/灯具/清洁 垂类定位，每账号独立品牌形象
- **定时任务**: 每 2 小时自动发布，9 品类轮换，内容不重复
- **全链路记录**: Notion 发布记录 + G 盘归档（原图/品牌图/视频/meta.json）

## 架构

```
scripts/auto_publish.py              (定时任务入口)
  → src/content_pool.py              (9 品类 + Firecrawl 抓图 + 长文案生成)
  → src/brand_template.py            (RAQM 阿拉伯语品牌模板)
  → src/video_maker.py               (Ken Burns + BGM + 5 slides + 多过渡)
  → src/publisher.py                 (双轨调度: API / 浏览器)
    → src/publisher_browser.py       (AdsPower + Selenium + 发布验证)
    → src/publisher_api.py           (TikTok Content Posting API)
  → src/notion_log.py                (Notion 发布记录)
  → src/accounts.py                  (账号管理 + portalocker)
  → src/adspower.py                  (AdsPower 本地 API)
  → src/oauth.py                     (OAuth 2.0 + PKCE)
  → src/cdn.py                       (Cloudflare R2 CDN)
```

## 9 品类

| 品类 | 阿拉伯语 | IKEA 分类 |
|------|---------|-----------|
| kitchen_storage | تنظيم المطبخ | kitchen-storage-organisation |
| bathroom | إكسسوارات الحمام | bathroom-accessories |
| home_decoration | ديكور المنزل | home-decoration |
| laundry | تنظيم الغسيل | laundry-cleaning |
| lighting | إضاءة | lighting |
| kitchen_trolleys | عربات المطبخ | kitchen-islands-trolleys |
| shelving_units | وحدات الأرفف | shelving-units |
| chest_of_drawers | أدراج وخزائن | chest-of-drawers |
| shoe_storage | تخزين الأحذية | shoe-storage |

## 5 账号矩阵

| 账号 | 定位 | 名称 |
|------|------|------|
| sa_02 | 厨房 | مطبخ أنيق \| Elegant Kitchen |
| sa_03 | 家居 | بيت مرتب \| Tidy Home |
| sa_04 | 浴室 | حمامي الأنيق \| My Chic Bath |
| sa_05 | 灯具 | إضاءة وأجواء \| Light & Mood |
| sa_06 | 清洁 | نظافة وترتيب \| Clean & Tidy |

## 使用

```bash
# 定时自动发布（所有活跃账号）
python scripts/auto_publish.py

# 指定账号
python scripts/auto_publish.py --accounts tiktok_sa_02 tiktok_sa_03

# 单账号 CLI
python scripts/publish.py --account tiktok_sa_02 \
  --title "Kitchen Organizer" --images photos/*.jpg

# 试运行
python scripts/auto_publish.py --dry-run
```

## 关键经验

1. **TikTok 网页版只支持视频** — 图片必须先转为 Ken Burns 轮播视频
2. **最少 5 张 slides** — 不足时复制补充，配合不同 zoom/pan 效果保持多样性
3. **RAQM 引擎** — Pillow 的 RAQM layout engine 正确渲染阿拉伯语 RTL 文字
4. **React onClick 触发** — TikTok 的 Post 按钮需要通过 React fiber 触发，DOM click 无效
5. **发布后必须验证** — 导航到 profile 对比视频数量，80% 成功率
6. **设备指纹关联** — 被封账号的手机绝不能登录新账号，只用 AdsPower
7. **白号封号率 37%** — 建议买满月号或千粉号
8. **TikTok Studio** — 修改账号资料需要通过 tiktokstudio 桌面端，移动端不支持

## 配置

### 环境变量 (.env)

```bash
# TikTok Developer App (API 模式)
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=

# Cloudflare R2 (API 模式 CDN)
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=

# Notion (发布记录)
NOTION_TOKEN=
NOTION_PUBLISH_DB=

# 归档
TIKTOK_ARCHIVE_DIR=G:/TikTok发布归档

# 代理
PROXY_HOST=gate.nodemaven.com
PROXY_PORT=8080
PROXY_USER=
PROXY_PASSWORD=
```

## 版本历史

### v2.0 (2026-04-03)
- Firecrawl 多角度产品图抓取 + 质量筛选（分辨率/色彩/去白底）
- RAQM 阿拉伯语品牌模板（品牌栏 + ترشيح مميز badge + 模糊背景）
- Ken Burns zoom/pan 视频效果 + 免版权 BGM + 4 种过渡
- 最少 5 slides / 15 秒视频
- Gulf 方言长文案（8-10 行阿拉伯语 + 英文推荐风格）
- 发布后 profile 验证 + 失败自动重试
- Notion 发布记录 + G 盘归档
- 每 2 小时定时任务（5 账号 × 9 品类轮换）
- 5 账号垂类定位 + 品牌头像
- 三方审核修复（Codex + code-reviewer + architect）
- 新增 4 个 IKEA 品类（手推车/架子/抽屉/鞋柜）

### v1.0 (2026-04-02)
- 初始版本
- 图片→视频轮播 (FFmpeg xfade)
- AdsPower + Selenium 浏览器自动化
- 多账号批量发布
- 双轨调度 (API + 浏览器)
