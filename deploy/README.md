# AquaVir-KB 部署指南
## NAR Database Issue 2028 投稿用

### 前置条件
- Docker 24+ / Docker Compose v2
- 域名 `aquavir-kb.org`（或测试用 localhost）
- 服务器：2 CPU / 4 GB RAM / 50 GB SSD（最低）

---

## 部署清单（从零到上线）

### 第一步：租用云服务器

云服务器就是按月"租"的，不需要买断。按以下步骤操作：

#### 推荐方案：阿里云香港 ECS（免备案，当天上线）

1. 打开 https://ecs.aliyun.com ，登录（支付宝/淘宝账号即可）
2. 点击「创建实例」
3. 关键参数：
   - **地域**：香港（或新加坡）
   - **实例规格**：2 vCPU / 4 GiB（ecs.c6.large 或 ecs.g6.large）
   - **系统镜像**：Ubuntu 22.04 LTS
   - **系统盘**：50 GB SSD 云盘
   - **网络**：分配公网 IPv4，按量带宽计费（5 Mbps 峰值足够学术网站）
   - **购买时长**：先选 1 个月试用，稳定后改年付（更便宜）
4. 点击「立即购买」→ 支付宝付款
5. 等 2-5 分钟，实例变为「运行中」状态
6. 在控制台找到「公网 IP」，记下来

> **费用参考**：香港轻量应用服务器（2核4G 50GB）约 ¥100-150/月，或按量计费约 $15-25/月。
> 腾讯云香港轻量服务器也是一个好选择：https://cloud.tencent.com/product/lighthouse

#### 备选：阿里云国内（需 ICP 备案，15-20 工作日）

如果后续需要国内低延迟访问，在备案完成后迁移即可。备案期间先用香港服务器运行。

#### 你需要做的

1. 打开上面链接注册/登录（用支付宝就行）
2. 按照上面参数选配置
3. 付款
4. 把公网 IP 告诉我，我们继续下一步

### 第二步：域名与 DNS

```bash
# 1. 购买域名 aquavir-kb.org（如未购买）
# 2. 在域名管理后台添加 A 记录：
#    aquavir-kb.org  →  <服务器公网IP>
#    www.aquavir-kb.org  →  <服务器公网IP>
# 3. 等待 DNS 生效（通常 5-30 分钟）
# 验证：
nslookup aquavir-kb.org
```

### 第三步：服务器基础配置

```bash
# SSH 登录服务器
ssh root@<服务器IP>

# 安装 Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# 验证
docker --version
docker compose version
```

### 第四步：上传代码并部署

在本地 Windows 上执行：

```powershell
# 打包 deploy 目录（排除 .env 敏感文件）
cd F:\水生无脊椎动物数据库
tar --exclude='.env' -czf deploy.tar.gz deploy/

# 上传到服务器（用 scp 或其他工具）
scp deploy.tar.gz root@<服务器IP>:/opt/
```

在服务器上执行：

```bash
cd /opt
tar -xzf deploy.tar.gz
cd deploy

# 1. 创建环境变量
cp .env.example .env
nano .env  # 修改 DB_PASSWORD 为强密码

# 2. 准备种子数据
mkdir -p seed_data
cp /path/to/public_download/*.tsv seed_data/  # 如果有

# 3. 启动所有服务
docker compose up -d

# 4. 查看启动状态
docker compose ps
docker compose logs -f
```

### 第五步：配置 HTTPS（Let's Encrypt 免费证书）

```bash
# 安装 certbot
apt install -y certbot

# 先停止 nginx（SSL 证书路径还没准备好时 nginx 会启动失败）
docker compose stop nginx

# 申请证书
certbot certonly --standalone -d aquavir-kb.org -d www.aquavir-kb.org

# 证书默认在 /etc/letsencrypt/live/aquavir-kb.org/
# 重新启动所有服务
docker compose up -d
```

### 第六步：验证部署

```bash
# 健康检查
curl https://aquavir-kb.org/api/health

# 验证页面
curl -I https://aquavir-kb.org/
# 检查返回头中有 HSTS、X-Content-Type-Options 等安全头

# 测试 API 文档
curl -I https://aquavir-kb.org/docs

# 测试搜索
curl "https://aquavir-kb.org/api/search?q=test"
```

手动浏览器检查：
- [ ] 首页正常加载（无 CDN 依赖缺失）
- [ ] 搜索功能可用
- [ ] 病毒详情页可用
- [ ] 统计图表正常（ECharts）
- [ ] 下载区可访问
- [ ] Swagger UI（`/docs`）正常
- [ ] HTTPS 绿色锁头
- [ ] 手机浏览器布局正常

### 第七步：证书自动续期

```bash
# 添加 cron 任务（每月 1 号凌晨续期）
crontab -e
# 添加这行：
0 3 1 * * certbot renew --quiet --pre-hook "docker compose -f /opt/deploy/docker-compose.yml stop nginx" --post-hook "docker compose -f /opt/deploy/docker-compose.yml start nginx"
```

---

### 访问地址

| 服务 | URL |
|------|-----|
| Web 前端 | https://aquavir-kb.org |
| REST API | https://aquavir-kb.org/api/ |
| Swagger UI | https://aquavir-kb.org/docs |
| ReDoc | https://aquavir-kb.org/redoc |
| 数据下载 | https://aquavir-kb.org/downloads/ |

### 常用运维命令

```bash
# 查看日志
docker compose logs -f api

# 重启单个服务
docker compose restart api

# 更新代码后重新构建
docker compose build api
docker compose up -d api

# 数据库备份
docker compose exec db pg_dump -U aquavir aquavir_kb > backup_$(date +%Y%m%d).sql

# 全部停止
docker compose down
```

### 数据导入流程

1. SQLite → PostgreSQL 迁移：`python migrate_sqlite_to_pg.py`
2. 从 public_download/*.tsv 导入 PostgreSQL
3. 创建索引和全文检索

### Zenodo DOI 注册

1. 打包 public_download/ 为 aquavir-kb-v1.0.zip
2. 上传至 https://zenodo.org/deposit
3. 元数据：
   - Title: AquaVir-KB: A comprehensive knowledge base for aquatic invertebrate viruses
   - Keywords: virus, aquatic invertebrate, database, aquaculture, metagenomics
   - License: CC-BY 4.0
4. 获取 DOI（格式：10.5281/zenodo.XXXXXXX）
5. 在论文和 README 中引用

### NAR 投稿 checklist

- [ ] URL 公开可访问，无登录墙
- [ ] HTTPS 已启用
- [ ] 搜索/浏览功能可用
- [ ] 数据下载功能可用
- [ ] About 页面含引用说明
- [ ] API 文档可访问
- [ ] 手机端基本可用
- [ ] 域名承诺维持至少 5 年
