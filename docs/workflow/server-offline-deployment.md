# 轻量服务器 Docker 离线部署与更新工作流

本文记录油训智安项目当前采用的服务器部署方式，适用于以下环境：

- 服务器架构：`x86_64` / `linux/amd64`
- 服务器规格：2 核、约 2 GB 内存
- 部署目录：`/root/agent-oil`
- 部署方式：本地构建镜像，使用 `docker save`、`scp`、`docker load` 离线发布
- 公网入口：Nginx 的 HTTP 80 端口

文档中的 `<SERVER_IP>`、`<PEM_KEY_PATH>` 和 `<VERSION>` 都是占位符。不要把真实密码、PEM 私钥、API Key 或生产 `.env` 提交到 Git。

## 1. 部署架构

```text
本地开发机
  ├─ 构建 linux/amd64 后端镜像
  ├─ 构建 linux/amd64 前端镜像
  └─ docker save 导出 tar
             │
             │ scp
             ▼
轻量应用服务器
  ├─ docker load 导入镜像
  └─ Docker Compose 启动服务
       ├─ PostgreSQL
       ├─ Qdrant
       ├─ Backend
       ├─ Frontend Nginx
       └─ Edge Nginx :80
```

公网请求链路：

```text
浏览器 → 服务器:80 → Edge Nginx
                         ├─ 页面请求 → Frontend
                         └─ /api/*  → Backend
                                         ├─ PostgreSQL
                                         └─ Qdrant
```

服务器覆盖配置使用 `docker-compose.server.yml`，主要作用如下：

| 服务 | 镜像/用途 | 内存上限 | 宿主机端口 |
|---|---|---:|---|
| postgres | PostgreSQL 16 | 320 MiB | 不公开 |
| qdrant | Qdrant 1.11.3 | 512 MiB | 不公开 |
| backend | `agent-oil-backend:<VERSION>` | 512 MiB | 不公开 |
| frontend | `agent-oil-frontend:<VERSION>` | 48 MiB | 不公开 |
| nginx | Nginx 1.27 | 48 MiB | `80` |

`backend` 和 `frontend` 的 `build` 配置在服务器覆盖文件中被清除，防止误在低内存服务器上构建镜像。

## 2. 持久化数据

当前使用以下 Docker 命名卷：

| 数据 | Docker 卷 |
|---|---|
| PostgreSQL | `oil-train-safe_postgres-data` |
| Qdrant | `oil-train-safe_qdrant-data` |
| 上传文件 | `oil-train-safe_uploads-data` |

普通的容器更新和重新创建不会删除这些数据。

严禁在没有备份和明确确认的情况下执行：

```bash
docker compose down -v
```

其中 `-v` 会删除数据卷。

## 3. 首次部署

### 3.1 本地构建应用镜像

在项目根目录执行。版本号示例为 `v1`。

后端：

```powershell
docker build --platform linux/amd64 `
  -f docker/Dockerfile.backend `
  -t agent-oil-backend:v1 .
```

前端：

```powershell
docker build --platform linux/amd64 `
  -f docker/Dockerfile.frontend `
  -t agent-oil-frontend:v1 ./frontend
```

拉取首次部署所需的基础镜像：

```powershell
docker pull postgres:16-alpine
docker pull qdrant/qdrant:v1.11.3
docker pull nginx:1.27-alpine
```

### 3.2 导出完整离线镜像包

首次部署需要包含五个镜像：

```powershell
docker save -o agent-oil-images-v1-amd64.tar `
  agent-oil-backend:v1 `
  agent-oil-frontend:v1 `
  postgres:16-alpine `
  qdrant/qdrant:v1.11.3 `
  nginx:1.27-alpine
```

生成 SHA256：

```powershell
Get-FileHash .\agent-oil-images-v1-amd64.tar -Algorithm SHA256
```

### 3.3 上传镜像和配置

服务器应提前安装 Docker、Docker Compose，并将仓库放在 `/root/agent-oil`。

```powershell
scp -i "<PEM_KEY_PATH>" `
  .\agent-oil-images-v1-amd64.tar `
  root@<SERVER_IP>:/root/agent-oil/
```

```powershell
scp -i "<PEM_KEY_PATH>" `
  .\docker-compose.server.yml `
  root@<SERVER_IP>:/root/agent-oil/
```

不要上传本地开发 `.env` 覆盖服务器的生产 `.env`。服务器 `.env` 应手动配置，并至少满足：

- `APP_ENV=production`
- `APP_DEBUG=false`
- 使用随机且足够长的 `PG_PASSWORD`
- 使用随机且足够长的 `JWT_SECRET`
- 正确配置生产 API Key
- 低内存服务器建议 `UPLOAD_MAX_SIZE_MB=5`

### 3.4 服务器加载镜像

```powershell
ssh -i "<PEM_KEY_PATH>" root@<SERVER_IP>
```

```bash
cd /root/agent-oil
sha256sum agent-oil-images-v1-amd64.tar
docker load -i agent-oil-images-v1-amd64.tar
```

确认镜像架构：

```bash
docker image inspect \
  agent-oil-backend:v1 \
  agent-oil-frontend:v1 \
  postgres:16-alpine \
  qdrant/qdrant:v1.11.3 \
  nginx:1.27-alpine \
  --format '{{.RepoTags}} {{.Os}}/{{.Architecture}}'
```

所有镜像都应显示为 `linux/amd64`。

### 3.5 配置 Swap

2 GB 服务器建议配置 2 GB Swap，避免短时内存峰值导致 SSH 和整机失去响应。创建前应先执行 `swapon --show`，避免重复创建。

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
```

在 `/etc/fstab` 中加入：

```text
/swapfile none swap sw 0 0
```

验证：

```bash
free -h
swapon --show
```

### 3.6 启动服务

先检查合并配置是否能解析：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  config --quiet
```

不要把完整的 `docker compose config` 输出保存到日志，因为它可能展开 `.env` 中的敏感值。

启动时必须使用 `--no-build`：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  up -d --no-build
```

## 4. 全新数据库的首次引导限制

当前迁移链在完全空的 PostgreSQL 数据库上存在已知问题：部分 Alembic 迁移引用基础表时，基础表可能尚未创建。

现有服务器已经完成首次引导，保留 PostgreSQL 数据卷时不会重复遇到这个问题。

只有在确认数据库为全新空库、没有业务数据且 `alembic current` 没有版本时，才可以执行以下一次性流程：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  up -d --no-build postgres qdrant
```

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  run --rm --no-deps backend python -m app.seed
```

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  run --rm --no-deps backend alembic stamp head
```

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  up -d --no-build
```

不要对来源不明或已经存在业务表的数据库直接执行 `alembic stamp head`。应优先从代码层修复迁移链，再用于新的生产环境。

## 5. 日常版本更新

推荐为每次发布使用新标签，例如从 `v1` 更新到 `v2`。不要直接覆盖旧标签，以便快速回滚。

### 5.1 根据改动范围选择镜像

| 改动内容 | 需要处理的镜像/文件 |
|---|---|
| Python 后端代码或依赖 | 重新构建 backend |
| Vue 前端代码或依赖 | 重新构建 frontend |
| 前后端都修改 | 重新构建两个应用镜像 |
| `docker/nginx/nginx.conf` | 上传配置文件，重建 nginx 容器 |
| `docker/nginx-frontend.conf` | 上传配置文件，重建 frontend 容器 |
| `docker-compose.server.yml` | 上传覆盖文件，重新执行 `up` |
| 生产环境变量 | 手动合并服务器 `.env`，重建受影响容器 |
| 数据库模型或迁移 | 先备份数据库，再更新 backend |

仅执行 `git pull` 不会更新正在运行的应用，因为代码已经打包进 Docker 镜像。

### 5.2 构建新版本

以同时更新前后端到 `v2` 为例：

```powershell
docker build --platform linux/amd64 `
  -f docker/Dockerfile.backend `
  -t agent-oil-backend:v2 .
```

```powershell
docker build --platform linux/amd64 `
  -f docker/Dockerfile.frontend `
  -t agent-oil-frontend:v2 ./frontend
```

同步修改 `docker-compose.server.yml`：

```yaml
backend:
  image: agent-oil-backend:v2

frontend:
  image: agent-oil-frontend:v2
```

### 5.3 导出增量应用包

基础镜像版本没有变化时，日常更新只需打包应用镜像：

```powershell
docker save -o agent-oil-app-v2-amd64.tar `
  agent-oil-backend:v2 `
  agent-oil-frontend:v2
```

```powershell
Get-FileHash .\agent-oil-app-v2-amd64.tar -Algorithm SHA256
```

如果只更新后端，可以只保存后端镜像。

### 5.4 发布前备份

涉及数据库模型、迁移或重要业务逻辑时，优先创建阿里云服务器快照。

也可以导出 PostgreSQL：

```bash
mkdir -p /root/agent-oil/backups
docker exec ots-postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > /root/agent-oil/backups/postgres-before-v2.sql
```

确认备份文件非空后再继续发布。

### 5.5 上传并导入新版本

```powershell
scp -i "<PEM_KEY_PATH>" `
  .\agent-oil-app-v2-amd64.tar `
  root@<SERVER_IP>:/root/agent-oil/
```

```powershell
scp -i "<PEM_KEY_PATH>" `
  .\docker-compose.server.yml `
  root@<SERVER_IP>:/root/agent-oil/
```

登录服务器后：

```bash
cd /root/agent-oil
sha256sum agent-oil-app-v2-amd64.tar
docker load -i agent-oil-app-v2-amd64.tar
```

### 5.6 更新容器

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  config --quiet
```

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  up -d --no-build
```

Compose 会重新创建镜像标签发生变化的容器，命名卷中的数据库、向量数据和上传文件会继续保留。

## 6. 发布验证

查看容器状态：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  ps
```

检查服务器内部完整链路：

```bash
curl -fsS http://127.0.0.1/api/health/live
```

期望响应：

```json
{"success":true,"data":{"status":"alive"}}
```

查看日志：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  logs --tail=100 backend nginx
```

检查资源与 OOM：

```bash
docker stats --no-stream
```

```bash
docker inspect \
  ots-postgres ots-qdrant ots-backend ots-frontend ots-nginx \
  --format '{{.Name}} restart={{.RestartCount}} oom={{.State.OOMKilled}}'
```

检查宿主机端口：

```bash
ss -lntp
```

应用服务应只公开 80；PostgreSQL 5432、Qdrant 6333/6334 和 Backend 8000 不应出现在宿主机公网监听列表中。

最后从开发机或浏览器验证：

```text
http://<SERVER_IP>/
http://<SERVER_IP>/api/health/live
```

## 7. 回滚

在确认新版本稳定之前，保留旧镜像和旧版 `docker-compose.server.yml`。

发生问题时，将镜像标签改回上一版本，例如：

```yaml
backend:
  image: agent-oil-backend:v1

frontend:
  image: agent-oil-frontend:v1
```

然后执行：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.server.yml \
  up -d --no-build
```

回滚应用镜像不会自动回滚数据库结构。如果新版本包含数据库迁移，必须提前设计对应的数据库回滚或恢复备份方案。

## 8. 发布后清理

所有验证通过后，可删除服务器上的传输包以节省磁盘：

```bash
rm -- /root/agent-oil/agent-oil-app-v2-amd64.tar
```

本地 tar 建议保留一段时间，作为离线回滚包。

不要在确认回滚不再需要之前运行：

```bash
docker image prune -a
docker system prune -a
```

## 9. 安全要求

- 不提交 `.env`、`deploy.env`、PEM 私钥或镜像 tar。
- 不在命令、截图、日志或文档中记录密码和 API Key。
- 不直接将 PostgreSQL、Qdrant 或 Backend 端口暴露到公网。
- 修改服务器 `.env` 前先备份，并保持文件权限为 `600`。
- SSH 私钥只保存在受控位置，不复制进仓库。
- 对外正式使用时应配置域名与 HTTPS 443。
- 已经在聊天、日志或公开位置出现过的密码应立即轮换。

## 10. 常用排障命令

```bash
free -h
swapon --show
df -h
docker stats --no-stream
docker compose -f docker-compose.yml -f docker-compose.server.yml ps
docker compose -f docker-compose.yml -f docker-compose.server.yml logs --tail=200
dmesg -T | grep -Ei 'out of memory|oom|killed process'
```

如果服务器在构建阶段卡死，首先确认是否误用了 `--build`。本工作流要求所有镜像在本地构建，服务器只执行 `docker load` 和 `up --no-build`。
