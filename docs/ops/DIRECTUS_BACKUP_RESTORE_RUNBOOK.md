# Directus 备份与恢复 Runbook

覆盖 Directus PostgreSQL（`k8s-netlab-postgres` 容器）+ `data/directus/uploads` +
`data/directus/extensions`，以及既有的 `data/*.json`。三者由
`scripts/backup-full-state.sh` 统一编排，产出到 `/root/backups/k8s-netlab-full/<timestamp>/`。

关联脚本：
- `scripts/backup-full-state.sh` — 每日编排入口（flock + staging + checksum 校验 + 原子 promote + 保留策略）
- `scripts/backup-directus.sh` — pg_dump（custom format）+ uploads/extensions 归档
- `scripts/backup-data.sh` — `data/*.json` 备份（原有脚本，被上面两者复用，也可独立运行）

---

## 手工执行一次备份

```bash
bash /root/k8s-netlab/scripts/backup-full-state.sh
```

成功时退出码 0，日志按步骤打印 `[STEP]`，最终打印 promote 后的目录路径和
`当前保留完整备份数量`。任一步骤失败（pg_dump 失败、归档失败、checksum
不匹配、空文件）都会以非零退出码终止，**不会**产出到正式备份目录——staging
临时目录会被自动清理，不留半成品。

## 查看最近可用备份

```bash
ls -la /root/backups/k8s-netlab-full/ | tail -10
cat /root/backups/k8s-netlab-full/<timestamp>/manifest.json
```

`manifest.json` 记录：`backup_id`、`created_at_utc`、`postgres_version`、每个文件的
`filename`/`size_bytes`/`sha256`，以及 `restore_config_files_needed`（恢复时还需要
哪个配置文件，不含该文件本身）。

## 校验 checksum

```bash
cd /root/backups/k8s-netlab-full/<timestamp>
python3 -c "
import hashlib, json
m = json.load(open('manifest.json'))
for f in m['files']:
    h = hashlib.sha256(open(f['filename'], 'rb').read()).hexdigest()
    status = 'OK' if h == f['sha256'] else 'MISMATCH'
    print(status, f['filename'])
"
```

---

## 在隔离环境恢复演练（不影响生产）

**绝不**对 `k8s-netlab-postgres`（生产容器）执行 `pg_restore`。恢复演练必须使用
一次性临时容器：

```bash
# 1. 起一个一次性 PostgreSQL 16 容器（随机密码，不复用生产密码）
DRILL_PW=$(openssl rand -hex 16)
docker run -d --name k8s-netlab-restore-drill \
  -e POSTGRES_USER=directus -e POSTGRES_PASSWORD="$DRILL_PW" -e POSTGRES_DB=directus \
  postgres:16-alpine

# 2. 等待就绪
until docker exec k8s-netlab-restore-drill pg_isready -U directus >/dev/null 2>&1; do sleep 1; done

# 3. 拷入最新 dump 并恢复（对全新数据库只执行一次 pg_restore，不要重复执行——
#    重复执行会因为对象已存在报大量 "already exists" 错误，这不代表数据损坏，
#    但会掩盖真实的失败信号，判断结果时必须以第一次执行的退出码为准）
DEST=/root/backups/k8s-netlab-full/<timestamp>
docker cp "$DEST/directus_postgres.dump" k8s-netlab-restore-drill:/tmp/restore.dump
docker exec -e PGPASSWORD="$DRILL_PW" k8s-netlab-restore-drill \
  pg_restore -U directus -d directus --no-owner --no-privileges /tmp/restore.dump

# 4. 核对关键表记录数是否与生产一致
for t in directus_users articles directus_files comments experiments; do
  echo -n "$t: "
  docker exec -e PGPASSWORD="$DRILL_PW" k8s-netlab-restore-drill \
    psql -U directus -d directus -t -c "SELECT count(*) FROM $t;"
done
# 对照生产（只读，不影响生产）：
source /root/k8s-netlab/.env.directus
for t in directus_users articles directus_files comments experiments; do
  echo -n "$t: "
  docker exec -e PGPASSWORD="$DIRECTUS_DB_PASSWORD" k8s-netlab-postgres \
    psql -U directus -d directus -t -c "SELECT count(*) FROM $t;"
done

# 5. 校验 uploads/extensions 归档内容
TMPX=$(mktemp -d)
tar xzf "$DEST/directus_uploads.tar.gz" -C "$TMPX"
tar xzf "$DEST/directus_extensions.tar.gz" -C "$TMPX"
diff -rq "$TMPX/uploads" /root/k8s-netlab/data/directus/uploads
diff -rq "$TMPX/extensions" /root/k8s-netlab/data/directus/extensions
rm -rf "$TMPX"

# 6. 清理临时容器（务必执行，不留残留资源）
docker rm -f k8s-netlab-restore-drill
```

演练判定标准：`pg_restore` 首次执行退出码为 0；关键表记录数与生产一致；
`diff -rq` 对 uploads/extensions 无输出（内容一致）；演练结束后
`docker ps` 中不再有 `k8s-netlab-restore-drill`。

---

## 失败排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `backup-directus.sh` 报 "容器不存在或未运行" | `k8s-netlab-directus`/`k8s-netlab-postgres` 未启动 | `docker compose -f docker-compose.directus.yml --env-file .env.directus up -d`，确认 healthy 后重跑备份 |
| pg_dump 失败 | 密码错误 / DB 连接被拒 | 核对 `.env.directus` 中 `DIRECTUS_DB_PASSWORD`；确认容器日志 `docker logs k8s-netlab-postgres` |
| checksum 校验失败 | staging 阶段文件被并发修改，或磁盘故障 | 不会被 promote 到正式目录，直接重跑一次 `backup-full-state.sh` |
| `[FATAL] 另一个 backup-full-state 任务正在运行` | flock 未释放（上一次任务仍在跑或异常挂起） | 确认 `ps aux \| grep backup-full-state` 是否真的还在跑；若确认卡死进程已不存在，锁文件本身无需手动清理（flock 随进程退出自动释放） |
| pg_restore 演练报大量 "already exists" | 对同一个数据库重复执行了 `pg_restore`（数据已在第一次跑成功） | 判断以首次执行的退出码为准；如需重试，先删除临时容器重新起一个全新的再恢复一次 |

---

## 保留策略

- 本地保留最近 **30 天**，`backup-full-state.sh` 每次运行时自动清理超期目录，且不会删除本次刚生成的备份
- 备份目录权限 `700`，文件权限 `600`
- `.env` / `.env.directus` **不在备份产物中**，`manifest.json` 只记录恢复时需要哪个配置文件，密钥本身需从原机器或密钥管理系统另行取得

## 异地恢复前置条件

当前状态：**`OFFSITE_BACKUP_NOT_CONFIGURED`**——本机之外没有配置任何异地备份目标
（未发现 rclone/restic 配置，未发现 age/GPG 密钥）。在异地备份目标就绪之前：

- 本地 `/root/backups/k8s-netlab-full/` 是唯一副本，与生产数据同处一台物理机，
  不构成真正的灾难恢复能力（同一机器故障会同时丢失生产数据和备份）
- 是否配置异地备份、使用什么目标（对象存储/另一台物理机等）、是否加密，
  需要 owner 决策；一旦决定，需要 owner 提供或授权生成加密密钥（本 runbook
  不会自行生成并托管新密钥）

---

## 凭证轮换（DIRECTUS_DB_PASSWORD / DIRECTUS_SECRET / DIRECTUS_ADMIN_PASSWORD）

**本节不记录任何密钥明文**，只记录方法和已验证过的操作顺序。

### 轮换前

1. 先跑一次 `bash scripts/backup-full-state.sh`，确认 checksum 全部通过——轮换失败需要回滚时，这是最后一道保险
2. 备份当前 `.env.directus` 到 `/root/backups/k8s-netlab-full/pre-rotation-env-<timestamp>.bak`，权限 600。这个备份文件本身包含轮换前的明文密钥（这是它作为可执行回滚方案的必要属性，不是疏漏），只应保留到确认新凭证稳定运行一段时间后，由 owner 决定何时清理

### 轮换三个值时的关键约束：新密钥绝不能出现在任何进程的 argv 里

`docker exec <container> <cmd> -e SOME_SECRET=xxx` 或 `... --password xxx` 这类写法，
密钥会作为 `docker exec`（或容器内被 exec 的进程）的命令行参数，本机任何用户
用 `ps auxww` / `/proc/<pid>/cmdline` 都能读到。正确做法是让密钥只经由 **stdin**
或**环境变量**传递，绝不作为命令行参数：

- **Postgres 角色密码**：`ALTER ROLE directus WITH PASSWORD '...'` 这条 SQL 连同
  用于认证的旧密码，一起通过 stdin 管道送进 `docker exec -i <container> sh -c
  'read -r AUTHPW; PGPASSWORD="$AUTHPW" psql -U directus -d directus -v ON_ERROR_STOP=1'`，
  psql 以脚本模式从 stdin 读取要执行的 SQL，全程没有任何一个进程的 argv 里出现密码
- **DIRECTUS_SECRET**：直接生成新值写入 `.env.directus`，重建 `directus` 容器即可
  （不需要经过网络请求，纯本地文件操作）
- **DIRECTUS_ADMIN_PASSWORD**：Directus 没有能"就地改别人密码"的安全 CLI 参数形式
  （`npx directus users passwd --email x --password y` 的 `--password` 同样会出现在
  该进程 argv 里），改用 REST API：用旧密码 `POST /auth/login` 换取 `access_token`，
  再用该 token `PATCH /users/me` 设置新密码，请求体通过 Python `urllib`/`json.dumps`
  构造并直接发送（不落地为文件、不经过会把内容打进 argv 的 curl `-d` 参数）

### 重建范围

只重建 `directus` 容器（`docker compose -f docker-compose.directus.yml --env-file
.env.directus up -d directus`）。**不重启 `database`（Postgres）容器**——
`ALTER ROLE` 修改的密码是立即生效的，不需要重启 Postgres；Postgres 官方镜像的
`POSTGRES_PASSWORD` 环境变量只在数据卷首次初始化时生效，之后改动该变量对已有
角色的实际密码没有任何作用，重启 Postgres 除了增加一次不必要的短暂不可用窗口
之外没有意义。

### 验证顺序

1. `curl http://127.0.0.1:8055/server/health` 确认 directus 用新 DB 密码重连成功
2. 用旧 admin 密码登录应返回 401/403，用新 admin 密码登录应返回 200
3. 公开只读端点（`/items/articles`、`/items/experiments`）不需要认证，SECRET
   轮换不影响它们，应始终 200——这是"公开读者路径不受影响"最直接的验证信号
4. 没有专门的 Directus 非 admin 测试账号密码可用时，退而求其次：对一个真实存在
   的 learner 邮箱故意传错误密码探测，确认端点返回 401（证明认证管线在新
   SECRET 下正常处理请求），加上 admin 账号完整走通登录→鉴权的同一套代码路径，
   两者合起来作为"普通用户登录路径未受影响"的证据链，而不是新建一个账号来测试
5. 执行一次 `backup-full-state.sh` + 隔离容器 `pg_restore` 演练，确认新密码下
   备份链路完整可用

### 已知的失败点（本 runbook 编写时踩过/预见的坑）

- `docker exec` 传密码永远走 stdin 或环境变量，不要贪图方便用 `-e`/`--password` 这类参数
- 轮换 Postgres 角色密码后**不要**顺手重启 `database` 容器——它不需要，而且会制造
  不必要的连接中断窗口
- 若轮换中途任一步骤失败，回滚顺序是：先还原 `.env.directus`，再把 Postgres
  角色密码 `ALTER` 回旧值（此时认证要用刚刚设置的新密码，因为它才是当前生效值），
  最后重建 `directus` 容器——顺序反了会导致 Directus 用还原后的旧密码去连接
  一个密码还没改回来的 Postgres，产生一次可避免的连接失败
