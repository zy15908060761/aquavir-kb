# AquaVir-KB 部署指南

## 准备

你的本地 Windows 电脑上，部署包已准备好：
```
F:\水生无脊椎动物数据库\deploy_full.tar.gz  (436 MB)
```

---

## 第一步：上传到服务器

打开 PowerShell 或 CMD，执行：

```powershell
# 替换 YOUR_SERVER_IP 为你的服务器 IP 地址
scp F:\水生无脊椎动物数据库\deploy_full.tar.gz root@YOUR_SERVER_IP:/opt/
```

输入服务器 root 密码，等待上传完成（约 3-8 分钟）。

---

## 第二步：SSH 登录服务器

```powershell
ssh root@YOUR_SERVER_IP
```

---

## 第三步：停止旧服务

```bash
cd /opt/deploy
docker compose down
```

---

## 第四步：备份旧数据库（安全起见）

```bash
cp /opt/deploy/data/crustacean_virus_core.db /opt/deploy/data/crustacean_virus_core_backup_$(date +%Y%m%d).db
```

---

## 第五步：解压新包

```bash
cd /opt
tar -xzf deploy_full.tar.gz
```

这会覆盖 `deploy/` 目录下的所有文件，并解压出 `sequences/` 目录。

---

## 第六步：确认文件正确

```bash
ls -lh /opt/deploy/data/crustacean_virus_core.db
# 应显示约 858M

ls /opt/deploy/backend.py
# 应存在

ls /opt/sequences/ | wc -l
# 应显示约 3898 个 FASTA 文件
```

---

## 第七步：创建 .env（如果还没有）

```bash
cd /opt/deploy
nano .env
```

输入以下内容，把密码改成强密码：
```
DB_PASSWORD=YourStrongPasswordHere123!
```

按 Ctrl+X，然后 Y，然后 Enter 保存。

---

## 第八步：启动服务

```bash
cd /opt/deploy
docker compose up -d --build
```

这会重建 API 镜像（包含最新的 backend.py、db_pg.py、模板），然后启动全部服务：

```
nginx (端口 80/443) → API (端口 8000) → SQLite 数据库
```

---

## 第九步：等待启动并检查

```bash
# 等 10 秒让服务启动
sleep 10

# 查看容器状态（3 个都应该是 Up）
docker compose ps

# 查看 API 日志（确认没有报错）
docker compose logs api | tail -30
```

---

## 第十步：验证功能

```bash
# 健康检查
curl https://aquavirdb.com/api/health

# 搜索 WSSV
curl "https://aquavirdb.com/api/search?q=WSSV&page_size=3"

# 首页
curl -I https://aquavirdb.com/

# 下载
curl -I https://aquavirdb.com/api/download/all_sequences.fasta
```

每个都应该返回 200 OK。

---

## 如果出问题

```bash
# 查看完整日志
docker compose logs -f

# 重启
docker compose restart

# 如果数据库有问题，恢复旧版本
cp /opt/deploy/data/crustacean_virus_core_backup_XXXXXXXX.db /opt/deploy/data/crustacean_virus_core.db
docker compose restart api
```

---

## 证书续期

Let's Encrypt 证书 90 天过期，需要定时续期：

```bash
crontab -e
```

添加：
```
0 3 1 * * certbot renew --quiet --pre-hook "docker compose -f /opt/deploy/docker-compose.yml stop nginx" --post-hook "docker compose -f /opt/deploy/docker-compose.yml start nginx"
```
