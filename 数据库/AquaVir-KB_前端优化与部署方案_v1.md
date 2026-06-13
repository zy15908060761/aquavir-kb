# AquaVir-KB 前端优化与部署方案 v1.0

> **目标**：适配 NAR 投稿评审要求，在 2核CPU / 4GB内存 / 60GB SSD 云服务器上实现专业、美观、高性能的数据库前端。
> **日期**：2025-06-13
> **数据规模**：SQLite 858MB / 111 张表 / 35万+ 证据记录 / 17,867 分离株 / 3,531 病毒物种 / 278 宿主物种

---

## 一、现状诊断与约束分析

### 1.1 数据资产清单

| 数据层 | 规模 | 关键表 |
|--------|------|--------|
| 病毒核心 | 3,531 物种 | `virus_master`, `virus_ictv_mappings`, `virus_aliases` |
| 分离株 | 17,867 条 | `viral_isolates`, `isolate_curated_profiles` |
| 宿主 | 278 物种 | `crustacean_hosts`, `host_biology_profiles`, `host_ecological_traits` |
| 蛋白 | 29,004 条 | `viral_proteins`, `protein_domains`, `protein_structures` |
| 文献证据 | 353,160 条 | `evidence_records`, `ref_literatures` (9,065 篇) |
| 感染记录 | 9,535 条 | `infection_records` |
| 爆发事件 | 56 条 | `outbreak_events` |
| 地理采样 | 4,317 条 | `sample_collections`, `gbif_occurrences` (4,039) |
| 外部富集 | 大量 | `interpro_annotations`(71,964), `kegg_annotations`(18,620), `uniprot_annotations`(11,351) |

### 1.2 服务器资源约束（硬性天花板）

| 资源 | 容量 | 限制分析 |
|------|------|----------|
| CPU | 2 核 | 最多 1 个 Uvicorn worker + nginx，Gunicorn 多进程不可行 |
| 内存 | 4 GB | Docker 容器 + SQLite 缓存 + 请求处理，可用约 3GB |
| 磁盘 | 60 GB SSD | 数据库 858MB + 序列文件估计 5-10GB + 部署文件，余量约 40GB |
| 网络 | 共享带宽 | 图片/地图资源必须 gzip + 缓存，不能大量传输 |

### 1.3 当前架构瓶颈

```
当前: nginx → FastAPI (2 workers, SQLite) → 每次请求 reopen DB
问题:
  - 2 workers × 2 连接 = 4 并发 DB 连接，SQLite 写锁会阻塞
  - 没有连接池，没有查询缓存
  - 首页同步加载 3 个 API（stats + top_viruses + genome_stats），瀑布请求
  - 模板中大量 JS 阻塞渲染（ECharts 同步 init）
  - 缺少暗色模式（NAR 审稿人夜间审稿刚需）
  - 详情页全部平铺，信息密度 > 3,000 字/屏，认知过载
```

---

## 二、架构优化方案（适配 2核4GB）

### 2.1 部署架构：精简单节点

```
┌─────────────────────────────────────────┐
│           Cloud Server (2C/4GB)          │
│  ┌─────────┐  ┌──────────────────────┐  │
│  │  nginx  │  │  FastAPI (1 worker)  │  │
│  │  :80/443│  │  :8000               │  │
│  │         │  │  - SQLite 只读模式   │  │
│  │  static │  │  - 内存查询缓存       │  │
│  │  cache  │  │  - Jinja2 模板渲染   │  │
│  └─────────┘  └──────────────────────┘  │
│       │              │                  │
│  ┌────▼──────────────▼──────────────┐  │
│  │      crustacean_virus_core.db    │  │
│  │      (858MB, 只读, PRAGMA cache)  │  │
│  └──────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**关键决策**：
- **只用 SQLite**，不部署 PostgreSQL（节省 1GB+ 内存）
- **1 个 Uvicorn worker**（`--workers 1`），避免 SQLite 锁竞争
- **nginx 静态文件缓存 + gzip**，降低后端压力
- **数据库连接池 + 只读模式**（`PRAGMA query_only = ON` 对公共端点）

### 2.2 SQLite 性能优化（部署级）

```sql
-- 数据库优化（一次性执行）
PRAGMA journal_mode = WAL;          -- 读写不阻塞
PRAGMA synchronous = NORMAL;        -- 降低 fsync 频率
PRAGMA cache_size = -64000;         -- 64MB 页缓存（约 256MB 内存）
PRAGMA temp_store = MEMORY;         -- 临时表存内存
PRAGMA mmap_size = 268435456;       -- 256MB 内存映射（减少 I/O）
PRAGMA optimize;                     -- 分析表统计信息
```

### 2.3 后端优化清单

| 优化项 | 实现 | 效果 |
|--------|------|------|
| 连接池复用 | `sqlite3.connect()` 改为 `threading.local()` 单连接 | 消除每次请求 reopen |
| 首页数据聚合 | 新增 `/api/dashboard` 单接口聚合 stats + top_viruses + genomes | 减少 3 次 HTTP 往返 |
| 查询结果缓存 | 字典缓存 `dashboard_cache_ttl = 300s` | 首页 90% 请求命中缓存 |
| 分页查询 | 所有列表接口 LIMIT + OFFSET | 防止内存溢出 |
| 暗色模式 | 后端不感知，纯前端 CSS `dark:` 类 | 零后端开销 |
| 静态文件分离 | nginx 直接 serve `/static/`, `/downloads/` | 不经过 FastAPI |

### 2.4 Dockerfile 修改

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY deploy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend.py api_models.py db_utils.py db_pg.py sync_runtime.py .
COPY templates/ templates/
COPY public_assets/ public_assets/
RUN mkdir -p /app/sequences /app/public_downloads
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1
# 关键：--workers 1 避免 SQLite 锁竞争，--limit-concurrency 防止内存爆
CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--limit-concurrency", "50", "--timeout-keep-alive", "65"]
```

### 2.5 docker-compose.yml 精简版

```yaml
version: '3.8'
services:
  api:
    build:
      context: ..
      dockerfile: Dockerfile
    volumes:
      - ./data:/app/data:ro          # 数据库只读挂载
      - ./data/sequences:/app/sequences:ro
      - ../public_downloads:/app/public_downloads:ro
    expose:
      - "8000"
    environment:
      - DATABASE_PATH=/app/data/crustacean_virus_core.db
      - SQLITE_CACHE_SIZE=-64000
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./static:/usr/share/nginx/html:ro
      - ../public_downloads:/usr/share/nginx/html/downloads:ro
      - certbot_www:/var/www/certbot:ro
      - ssl_certs:/etc/letsencrypt:ro
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - api
    restart: unless-stopped

volumes:
  ssl_certs:
  certbot_www:
```

---

## 三、前端设计优化方案（NAR 投稿级）

### 3.1 设计系统：Semantic Science Theme

基于全网调研（UniProt 2025, BV-BRC, NCBI Virus, ViralZone）和您现有数据，定义以下设计系统：

#### 色彩体系

```css
/* 主色：深海青绿 — 水生生物主题 */
--primary-50:  #f0fdfa;
--primary-100: #ccfbf1;
--primary-200: #99f6e4;
--primary-500: #14b8a6;
--primary-600: #0d9488;   /* 主按钮、链接 */
--primary-700: #0f766e;   /* 导航背景 */
--primary-800: #115e59;
--primary-900: #134e4a;

/* 数据语义色 — 每种数据类型固定颜色 */
--data-genome:     #3b82f6;   /* 蓝色：基因组/序列 */
--data-host:       #10b981;   /* 绿色：宿主/生态 */
--data-protein:    #8b5cf6;   /* 紫色：蛋白/结构 */
--data-virulence:  #f59e0b;   /* 橙色：致病性/爆发 */
--data-severe:     #ef4444;   /* 红色：高致死/紧急 */
--data-geography:  #06b6d4;   /* 青色：地理/分布 */
--data-literature: #64748b;   /* 灰色：文献/引用 */
--data-evidence:   #ec4899;   /* 粉色：证据/诊断 */

/* 背景层级 */
--bg-page:    #f8fafc;        /* Slate-50，比纯白更柔和 */
--bg-card:    #ffffff;
--bg-elevated:#f1f5f9;
--border-subtle: #e2e8f0;
--border-strong: #cbd5e1;

/* 暗色模式 */
--dark-bg-page:    #0f172a;   /* Slate-900 */
--dark-bg-card:    #1e293b;   /* Slate-800 */
--dark-bg-elevated:#334155;   /* Slate-700 */
--dark-text:       #f1f5f9;
--dark-text-muted: #94a3b8;
```

#### 字体层级

```css
/* 学术数据库排版：紧凑、信息密度高但可读 */
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, 
             "Noto Sans SC", "Noto Sans", "Helvetica Neue", sans-serif;

/* 层级 */
Display:  2.5rem / 700 / tracking-tight   /* 页面大标题 */
H1:       1.5rem / 600 / -0.01em         /* 区块标题 */
H2:       1.125rem / 600 / 0             /* 卡片标题 */
Body:     0.875rem / 400 / 0             /* 正文，14px 学术标准 */
Caption:  0.75rem / 500 / 0.02em         /* 标签、元数据 */
Mono:     "SF Mono", "Fira Code", monospace /* 登录号、GC% 等 */
```

#### 圆角与阴影（学术克制感）

```css
/* 圆角：比通用 UI 更小，显得更专业 */
--radius-sm:  4px;   /* 标签、小按钮 */
--radius-md:  6px;   /* 卡片、输入框 */
--radius-lg:  10px;  /* 大卡片、模态框 */

/* 阴影：几乎不可见，只提供层级暗示 */
--shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
--shadow-md: 0 1px 3px rgba(0,0,0,0.06), 0 2px 8px rgba(0,0,0,0.04);
--shadow-lg: 0 4px 12px rgba(0,0,0,0.06);
```

### 3.2 首页改造：Bento Grid + 数据叙事

当前首页是纵向堆叠的仪表盘，改造成 **Bento Grid**（日式便当盒）布局，每个格子是一个独立数据模块，视觉上更有节奏感。

```
┌────────────────────────────────────────────┐
│  Hero: AquaVir-KB                            │
│  水生无脊椎动物病毒知识库 · 知识枢纽            │
│  [搜索框________________________________]    │
│  [🦐 甲壳] [🐚 软体] [🪸 刺胞] [⭐ 棘皮] [🧽 海绵] │
├────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ 3,531    │  │ 17,867   │  │ 278      │  │
│  │ Viruses  │  │ Isolates │  │ Hosts    │  │
│  └──────────┘  └──────────┘  └──────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ 353K     │  │ 29K      │  │ 9K       │  │
│  │ Evidence │  │ Proteins │  │ Papers   │  │
│  └──────────┘  └──────────┘  └──────────┘  │
├────────────────────────────────────────────┤
│  ┌────────────────────┐  ┌────────────────┐  │
│  │ [饼图] Host Phylum  │  │ [柱状图] Top 10 │  │
│  │ Arthropoda 622      │  │ WSSV 1298      │  │
│  │ Mollusca 202        │  │ OsHV-1 803     │  │
│  └────────────────────┘  └────────────────┘  │
├────────────────────────────────────────────┤
│  ┌────────────────────────────────────────┐  │
│  │ 🌍 全球采样分布地图（缩略图，点击放大）  │  │
│  └────────────────────────────────────────┘  │
├────────────────────────────────────────────┤
│  📚 最新收录文献 · 爆发追踪 · 数据下载        │
├────────────────────────────────────────────┤
│  Cite us · API Docs · Data Availability ·  GitHub │
└────────────────────────────────────────────┘
```

**改造要点**：
- 统计数字采用 **"大数字 + 小标签 + 趋势箭头"** 三行结构
- 每个统计卡片边框使用对应数据语义色（病毒=teal, 蛋白=purple, 文献=slate）
- 宿主门快捷入口改为 **图标 + 渐变背景** 的胶囊按钮
- 地图区域使用缩略图，点击后全屏展开（减少首屏加载）

### 3.3 病毒详情页：渐进式披露（Progressive Disclosure）

当前问题：所有内容平铺，一屏内信息密度 > 3,000 字，用户找不到重点。

**改造方案：三层信息架构**

#### 第一层：Hero Summary（固定首屏）

```
┌────────────────────────────────────────────────────┐
│  White spot syndrome virus        [NCBI] [FASTA]  │
│  白斑综合征病毒 · WSSV                              │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │
│  Nimaviridae  >  Whispovirus  |  dsDNA  |  Arthropoda│
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │
│  🦠 1,298 分离株  │  🦐 98 宿主  │  🧬 156 蛋白  │  📄 5,570 证据│
│  ⚠️ 高致病性: 致死率 90-100%  │  🌍 40+ 国家检出    │
│  📋 1992年发现 · 全球大流行 · 年损失 >$10亿          │
└────────────────────────────────────────────────────┘
```

- 只展示最关键数据，用 emoji 图标 + 数字 + 简短说明
- 高致病性用橙色/红色高亮，建立视觉警觉
- 操作按钮（NCBI 外链、FASTA 下载）放在右侧

#### 第二层：主题 Tab（按需加载）

Tab 导航改为 **图标 + 文字 + 计数** 的紧凑样式：

```
┌────────────────────────────────────────────────────────┐
│  📋 概览 │ 🧬 基因组 │ 🦐 宿主 │ 🧪 蛋白 │ 📚 文献 │ 🌍 地理 │
│  当前: 概览（默认展开）                                  │
└────────────────────────────────────────────────────────┘
```

**Tab 内容策略**：
| Tab | 首屏展示 | 更多操作 |
|-----|----------|----------|
| 概览 | 基因组参数（6个指标卡）+ 致病性摘要 + 诊断方法（前3条） | 点击展开全部诊断 |
| 基因组 | 基因组长度、GC%、类型、完整度、NCBI 登录号 | 序列查看器（FASTA） |
| 宿主 | 关联宿主 Top 10（卡片网格）+ 证据等级标签 | 查看全部 98 宿主 |
| 蛋白 | 蛋白列表表格（前 20 条）+ 功能分类图例 | 分页加载 |
| 文献 | 核心文献（前 5 条）+ 证据来源统计 | 展开全部 |
| 地理 | 世界地图（懒加载）+ Top 10 国家列表 | 筛选年份/宿主 |

**关键交互**：
- **Tab 内容懒加载**：点击 Tab 时才通过 `fetch()` 获取数据，减少首屏 HTTP 请求
- **内联展开**：每个 Section 底部有 "Show all 156 proteins →" 按钮，展开后替换为分页
- **悬浮预览**：宿主名鼠标悬浮时显示小卡片（中文名、分类、感染记录数）

#### 第三层：详情弹窗/子页

- 蛋白详情：点击蛋白行 → 右侧滑出面板（名称、长度、功能、结构可用性、UniProt 链接）
- 文献详情：点击 PMID → 展开摘要 + 下载链接
- 分离株详情：点击登录号 → 新页面显示完整元数据 + 序列查看器

### 3.4 新增暗色模式（Dark Mode）

Tailwind CSS 支持 `dark:` 前缀，实现成本极低：

```html
<!-- base.html 中增加 -->
<html lang="en" class="dark">
  <script>
    // 自动检测系统偏好 + 本地存储记忆
    if (localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  </script>
```

```css
/* 所有背景/文字/边框使用 dark: 变体 */
.card {
  @apply bg-white border-slate-200;
  @apply dark:bg-slate-800 dark:border-slate-700 dark:text-slate-100;
}
```

NAR 审稿人经常在夜间审稿，暗色模式是**专业数据库的标配**（NCBI、UniProt、PDB 均已支持）。

### 3.5 搜索页：实时联动 + 结果直接操作

当前搜索页有 HTMX 局部刷新，但筛选器之间不联动。借鉴 NCBI Virus：

```
┌────────────────────────────────────────────┐
│  [搜索框: WSSV___________________] [Search]│
├────────────────────────────────────────────┤
│  Host Phylum          Genome Type          │
│  ☐ Arthropoda (622)  ☐ dsDNA (182)        │
│  ☐ Mollusca (202)    ☐ ssRNA(+) (890)     │
│  ☐ Cnidaria (18)      ☐ dsRNA (56)        │
│                                                       │
│  当选择 Arthropoda 后，Genome Type 的计数 │
│  应动态更新：dsDNA (150), ssRNA(+) (420)    │
├────────────────────────────────────────────┤
│  结果: 1-20 of 45 matching viruses         │
│  [Download CSV] [Download FASTA]            │
│  ──────────────────────────────────────     │
│  White spot syndrome virus ... [Details]    │
│  Taura syndrome virus      ... [Details]    │
└────────────────────────────────────────────┤
```

**改造**：
- 筛选条件变更后，通过 HTMX 请求 `/api/facet_counts` 更新各选项的计数
- 结果列表上方增加 **批量操作栏**（Download CSV / FASTA / JSON），这是 NAR 投稿数据库的必需功能
- 每行结果增加 **Quick View** 按钮：点击后右侧滑出详情面板，不打断列表浏览

### 3.6 新增页面：NAR 投稿必需

#### 3.6.1 Citation / About 页（必须）

NAR 数据库论文要求网站上有明确的引用信息：

```
┌────────────────────────────────────────────┐
│  Cite AquaVir-KB                           │
│  ─────────────────────────────────────────  │
│  AquaVir-KB: A comprehensive knowledge    │
│  base for aquatic invertebrate viruses.   │
│  Nucleic Acids Research, 2025.            │
│                                            │
│  [📋 BibTeX] [📋 EndNote] [📋 RIS]          │
│                                            │
│  ── Data Availability ──                 │
│  All data is freely available under CC-BY 4.0│
│  [Download Full Database]                  │
│                                            │
│  ── Funding ──                             │
│  ...                                       │
│  ── Contact ──                             │
│  ...                                       │
└────────────────────────────────────────────┘
```

#### 3.6.2 Data Release / Version 页（推荐）

展示数据库版本历史和更新日志，体现维护活性：

```
Version History
v1.0 (2025-06)  - 3,531 viruses, 17,867 isolates
v0.9 (2025-05)  - Added mollusk expansion
v0.8 (2025-04)  - Added protein structures
...
```

#### 3.6.3 Help / FAQ 页（现有，需扩充）

增加：
- "How to search" 动画演示
- "Data schema explained" 图表
- "How to download bulk data" 步骤说明
- "API quick start" 代码示例（Python + curl）

---

## 四、性能优化策略（适配资源限制）

### 4.1 前端资源优化

| 优化项 | 当前 | 目标 | 方法 |
|--------|------|------|------|
| JS 体积 | 3 个 CDN 文件（ECharts 500KB+） | < 200KB 首屏 | 首页图表用轻量 SVG + Canvas 按需加载 ECharts |
| CSS | Tailwind CDN 全量 | 仅使用的类 | 生产环境用 Tailwind CLI 生成 `tailwind.min.css` |
| 地图 | 1MB world.json 同步加载 | 首屏不加载 | 缩略图用 SVG 世界地图，点击后加载 ECharts |
| 字体 | 系统字体 | 系统字体 | 不引入自定义字体文件 |
| 图片 | 无 | 无 | 纯 CSS + SVG 图标，无位图 |

### 4.2 数据库查询优化

```python
# backend.py 中新增缓存层
import functools
import time

_dashboard_cache = {}
_dashboard_cache_ts = 0
CACHE_TTL = 300  # 5 分钟

@app.get("/api/dashboard")
def get_dashboard():
    global _dashboard_cache, _dashboard_cache_ts
    now = time.time()
    if now - _dashboard_cache_ts < CACHE_TTL and _dashboard_cache:
        return _dashboard_cache
    
    # 聚合查询：一次 SQL 拿到所有数据
    data = {
        "stats": _get_stats(),
        "top_viruses": _get_top_viruses(limit=10),
        "genome_stats": _get_genome_stats(),
        "phylum_distribution": _get_phylum_distribution(),
    }
    _dashboard_cache = data
    _dashboard_cache_ts = now
    return data
```

### 4.3 nginx 缓存配置

```nginx
# 在 nginx.conf 中增加
# 首页缓存 5 分钟（数据变化不频繁）
location = / {
    proxy_pass http://api:8000/;
    proxy_cache dashboard_cache;
    proxy_cache_valid 200 5m;
    proxy_cache_use_stale error timeout;
}

# API 响应缓存
location /api/ {
    proxy_pass http://api:8000/;
    proxy_cache api_cache;
    proxy_cache_valid 200 1m;  # API 缓存 1 分钟
    proxy_cache_valid 404 10s;
}

# 静态资源：长期缓存
location /static/ {
    alias /usr/share/nginx/html/;
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

---

## 五、部署执行清单

### 5.1 部署前准备（本地）

```bash
# 1. 生成 Tailwind CSS 生产文件（减少 90% 体积）
cd deploy/static
npx tailwindcss -o tailwind.min.css --minify

# 2. 验证数据库索引完整性
python -c "
import sqlite3
db = sqlite3.connect('crustacean_virus_core.db')
db.execute('PRAGMA optimize')
db.execute('PRAGMA integrity_check')
print('OK')
"

# 3. 压缩静态资源
find static/ -type f \( -name "*.js" -o -name "*.css" \) -exec gzip -k {} \;

# 4. 重新打包部署包
tar -czf deploy_full_v2.tar.gz deploy/ sequences/ public_downloads/ world.json china.json
```

### 5.2 服务器部署步骤

```bash
# 1. 上传
scp deploy_full_v2.tar.gz root@YOUR_SERVER:/opt/

# 2. 解压
ssh root@YOUR_SERVER "cd /opt && tar -xzf deploy_full_v2.tar.gz"

# 3. 优化数据库（一次性）
ssh root@YOUR_SERVER "sqlite3 /opt/deploy/data/crustacean_virus_core.db \"PRAGMA journal_mode=WAL; PRAGMA cache_size=-64000; PRAGMA optimize;\""

# 4. 启动
ssh root@YOUR_SERVER "cd /opt/deploy && docker compose up -d --build"

# 5. 验证
curl -s https://aquavirdb.com/api/health | jq .
curl -s "https://aquavirdb.com/api/search?q=WSSV&page_size=1" | jq '.results[0].canonical_name'
```

### 5.3 监控与告警

```bash
# 内存监控（关键：4GB 容易溢出）
# 在服务器添加 crontab：
*/5 * * * * free -m | awk '/Mem:/ {if ($3/$2 > 0.85) print "MEMORY ALERT"}' | logger

# 磁盘监控
0 * * * * df -h / | awk 'NR==2 {if ($5+0 > 85) print "DISK ALERT"}' | logger

# 服务自动重启（OOM 保护）
# docker-compose 中已配置 restart: unless-stopped
```

---

## 六、NAR 投稿检查清单

提交 NAR 数据库论文时，审稿人会实际访问网站。以下功能必须可用且稳定：

| 检查项 | 状态 | 说明 |
|--------|------|------|
| ✅ 网站在线可访问 | 现有 | aquavirdb.com 已部署 |
| ✅ 全局搜索 | 现有 | 病毒名、登录号、科/属 |
| ✅ 分面浏览 | 现有 | 宿主门、基因组类型等 |
| ✅ 病毒详情页 | 现有 | 多 Tab 信息聚合 |
| ✅ 宿主详情页 | 现有 | 生物学 + 地理 + 病毒关联 |
| ✅ 地理分布地图 | 现有 | 世界 + 中国 |
| ✅ 统计仪表盘 | 现有 | 数据质量指标 |
| ✅ 数据下载 | 现有 | FASTA / CSV / JSON |
| ✅ API 文档 | 现有 | OpenAPI / Redoc |
| ⚠️ **暗色模式** | **需新增** | 审稿人夜间使用刚需 |
| ⚠️ **引用页面** | **需增强** | Cite us / BibTeX / 数据可用性声明 |
| ⚠️ **渐进披露** | **需优化** | 详情页信息密度过高 |
| ⚠️ **移动端适配** | **需优化** | 审稿人可能用手机查看 |
| ⚠️ **加载性能** | **需优化** | 首页 3 个 API 瀑布请求 |
| ⚠️ **版本历史** | **需新增** | 体现数据库维护活性 |

---

## 七、实施优先级

基于 NAR 投稿时间节点和服务器约束，建议按以下顺序实施：

### Phase 1（本周，P0，投稿前必需）
1. **部署架构优化**：精简 Docker Compose，SQLite WAL 模式，单 worker
2. **性能优化**：首页聚合 API，查询缓存，nginx 静态缓存
3. **暗色模式**：全局 CSS `dark:` 改造，导航栏切换按钮
4. **Cite Us 页面**：BibTeX / EndNote / RIS 导出格式

### Phase 2（下周，P1，投稿前推荐）
5. **病毒详情页渐进式披露**：Tab 懒加载，内联展开，悬浮预览
6. **筛选器实时联动**：HTMX facet_counts API
7. **移动端响应式**：表格横向滚动，卡片堆叠，导航汉堡菜单
8. **版本历史页面**：展示数据库迭代过程

### Phase 3（投稿后，P2）
9. **Bento Grid 首页**：更现代的布局（可选）
10. **地图时间轴**：爆发事件的时空叙事
11. **AI 洞察卡片**：自动标注"近年激增"的病毒（利用已有爆发数据）

---

## 八、总结

您的 AquaVir-KB 已经具备了 **NAR 数据库论文的基础技术骨架**（FastAPI + SQLite + Jinja2 + 25+ 页面 + 完整的 API）。当前最大短板是**用户体验层**：

1. **性能**：2 核 4GB 的服务器需要精简架构（单 worker + SQLite + 缓存）
2. **体验**：详情页信息过载、缺少暗色模式、移动端未优化
3. **专业性**：引用页面、版本历史、数据可用性声明需要增强

上述方案全部可以在现有代码基础上渐进改造，**不需要重写框架或替换技术栈**。核心工作量：
- 前端 CSS/HTML 改造（约 30-40 小时）
- 后端缓存/聚合 API（约 10-15 小时）
- 部署配置优化（约 5 小时）

总计约 **1-2 周** 可完成 P0 + P1 的全部内容，满足 NAR 投稿评审要求。
