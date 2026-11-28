# 云服务器部署

把这台服务放到一台 Linux 云主机上，用域名通过 HTTPS 打开。页面和 `/api` 由同一个进程提供，浏览器始终访问你的域名，不需要单独配前端地址。

进程只监听 `127.0.0.1:8765`。对外只开放 80 和 443，由 Nginx 反代到本机。不要把 8765 和 Redis 的 6379 暴露到公网。

需要：

- 一台云主机，建议 Ubuntu 22.04 或 24.04，内存 1 GB 以上
- 域名 `tdsite.cn` 的 A 记录已经指向这台机器的公网 IP
- 云厂商安全组放行 TCP 22、80、443，不要放行 6379、8765
- 机器能访问外网。行情要连东方财富和新浪；放在境外的机器经常拉不到 A 股行情

## 1. 安装依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip redis-server nginx certbot python3-certbot-nginx git
```

构建页面还需要 Node.js 20。没有 `node` 时：

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

确认 `python3 --version` 至少是 3.11。

## 2. 放下代码

下面把代码放在 `/opt/td`。路径可以改，但后面的 systemd 和工作目录要一起改。

```bash
sudo mkdir -p /opt/td
sudo chown "$USER" /opt/td
git clone <你的仓库地址> /opt/td
cd /opt/td
python3 -m venv .venv
.venv/bin/pip install -e .
cd web && npm install && npm run build && cd ..
```

`pip install -e .` 会装上阿里云 OSS 的 `oss2`。自动备份用它上传，不另装包。

必须先构建出 `web/dist`，再启动进程。`/assets` 在进程启动时挂载；先启动后构建，页面样式和脚本会 404，需要再重启一次。

如果要把现有账本带上云，优先用第 8 节的 OSS 备份和恢复。还没有 OSS 备份时，只能整份拷贝：

- 每个用户的账本是 `data/users/{用户号}.db`
- 登录账号和会话在 Redis。只拷贝 SQLite、不迁 Redis，账本文件在，人也登不进去
- `data/td.db` 只在第一个注册用户还没有 `data/users/1.db` 时复制一次

把本机的 `data/users/` 拷到服务器的 `/opt/td/data/users/`。本机 Redis 如果是按 README 起在 `data/redis`，把该目录里的 `appendonly.aof` 和 `dump.rdb` 拷到服务器的 `/var/lib/redis/`，然后 `sudo systemctl restart redis-server`。两边 Redis 不要同时写同一份文件。

## 3. Redis

用系统自带的 Redis，只监听本机，并打开持久化。

```bash
sudo sed -i 's/^supervised .*/supervised systemd/' /etc/redis/redis.conf
sudo sed -i 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf
sudo sed -i 's/^appendonly .*/appendonly yes/' /etc/redis/redis.conf
sudo systemctl enable --now redis-server
redis-cli ping
```

应返回 `PONG`。不要设置 `TD_REDIS=memory`，那是测试用的，进程一停账号和会话就没了。

## 4. 用 systemd 常驻

```bash
sudo tee /etc/systemd/system/td.service >/dev/null <<'EOF'
[Unit]
Description=行情与仓位
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=REPLACE_USER
WorkingDirectory=/opt/td
Environment=TD_REDIS=redis://127.0.0.1:6379/0
Environment=TD_DATA_DIR=/opt/td/data/users
Environment=TD_LEGACY=/opt/td/data/td.db
Environment=TD_ADMINS=
Environment=TD_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
Environment=TD_OSS_BUCKET=tdsite
Environment=TD_OSS_ACCESS_KEY_ID=你的AccessKeyId
Environment=TD_OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
Environment=TD_OSS_PREFIX=td-backups
Environment=TD_BACKUP_INTERVAL=86400
Environment=TD_BACKUP_KEEP=14
ExecStart=/opt/td/.venv/bin/python -m td_api
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo sed -i "s/REPLACE_USER/$USER/" /etc/systemd/system/td.service
sudo systemctl daemon-reload
sudo systemctl enable --now td
sudo systemctl status td --no-pager
```

`WorkingDirectory` 必须是仓库根目录。账本路径不写绝对路径时，会相对这个目录。

Bucket 名称是 `tdsite`。`TD_OSS_ACCESS_KEY_ID` 和 `TD_OSS_ACCESS_KEY_SECRET` 按第 8 节在阿里云控制台创建。Bucket 还没建好、或密钥还没填时，先删掉 `TD_OSS_` 和 `TD_BACKUP_` 这几行再启动。留着占位密钥的话，网站能开，但会按间隔记一次备份失败。

在服务器上先确认本机已经起来：

```bash
curl -sS http://127.0.0.1:8765/api/health
```

返回里的 `backup.enabled` 为 true 才表示自动备份已打开。`backup.last_at`、`backup.last_key` 是最近一次成功的时间和对象名，`backup.last_error` 非空就是上次失败的原因。

## 5. 挂到域名

站点名用 `tdsite.cn` 和 `www.tdsite.cn`。两条 A 记录都要指向这台机器。平时用域名打开，不要用 `https://公网IP`。

先放业务站点，并去掉系统自带的 default，避免和后面的默认站点抢 80 端口：

```bash
sudo tee /etc/nginx/sites-available/td >/dev/null <<'EOF'
server {
    listen 80;
    server_name tdsite.cn www.tdsite.cn;

    client_max_body_size 4m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
EOF
sudo ln -sfn /etc/nginx/sites-available/td /etc/nginx/sites-enabled/td
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

签发证书并让 Nginx 跳转到 HTTPS。两个名字都要写进证书，证书目录一般是第一个名字，这台机器实际在 `/etc/letsencrypt/live/www.tdsite.cn/`：

```bash
sudo certbot --nginx -d www.tdsite.cn -d tdsite.cn
```

按提示填邮箱。完成后用浏览器打开 `https://tdsite.cn` 或 `https://www.tdsite.cn` 。证书到期前 certbot 会自动续期，可以用 `sudo certbot renew --dry-run` 看一眼。

页面路由在 `#` 后面，例如 `https://tdsite.cn/#positions`。Nginx 不用另做前端路由。

证书签好之后，再加一个默认站点。业务站点只匹配这两个域名。如果 80/443 没有 `default_server`，用公网 IP 访问、或者 HTTPS 没有带对域名（SNI）时，Nginx 没有可匹配的 server，会在 TLS 握手或读 HTTP 的阶段直接关掉连接。客户端看到的就是 `Remote end closed connection without response`，而不是一张普通的错误页。

默认站点要返回明确的 HTTP 状态。不要写 `return 444`，444 就是不回任何内容、直接断开，会把这个报错再造出来。

```bash
sudo tee /etc/nginx/sites-available/default-ip >/dev/null <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 403;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_certificate /etc/letsencrypt/live/www.tdsite.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/www.tdsite.cn/privkey.pem;
    return 403;
}
EOF
sudo ln -sfn /etc/nginx/sites-available/default-ip /etc/nginx/sites-enabled/default-ip
sudo nginx -t && sudo systemctl reload nginx
```

如果 `ls /etc/letsencrypt/live/` 里的目录不是 `www.tdsite.cn`，把上面两行证书路径改成实际目录。

检查时，裸 IP 应该是 403，域名仍然是正常页面：

```bash
curl -sI http://127.0.0.1 --max-time 5 | head -1
curl -skI https://127.0.0.1 --max-time 5 | head -1
curl -sI https://tdsite.cn --max-time 5 | head -1
```

前两行是 `HTTP/1.1 403 Forbidden`。最后一行是 `HTTP/1.1 200 OK`，或先 `301` 再打开 HTTPS。业务只从域名进。

## 6. 第一个账号

打开域名后先注册。第一个注册成功的用户是管理员，能看和改所有人的账本。之后的用户只能操作自己的。

想指定管理员时，编辑 `/etc/systemd/system/td.service` 里的 `TD_ADMINS`，多个用户名用英文逗号隔开，然后：

```bash
sudo systemctl daemon-reload
sudo systemctl restart td
```

## 7. 更新

```bash
cd /opt/td
git pull
.venv/bin/pip install -e .
cd web && npm install && npm run build && cd ..
sudo systemctl restart td
```

改过前端之后要重启。否则旧进程可能还没挂上新的静态文件。`pip install -e .` 会把 `oss2` 一起装上。

## 8. 备份、迁移和恢复

每个备份包里有两样东西：`/opt/td/data/users/*.db` 里每个用户的账本，以及 Redis 中 `td:` 开头的键（用户名、密码哈希、登录会话、股票名称缓存）。可选地带上 `data/td.db`。别的 Redis 数据不会放进包里，恢复时也不会删掉。

### 在阿里云拿到 Bucket 和 AccessKey

用主账号登录 [阿里云控制台](https://home.console.aliyun.com/)。不要创建主账号自己的 AccessKey。

Bucket 名称是 `tdsite`，对应环境变量 `TD_OSS_BUCKET=tdsite`。

1. 顶部搜索「对象存储 OSS」，打开 [Bucket 列表](https://oss.console.aliyun.com/bucket)。
2. 点「创建 Bucket」。
3. Bucket 名称填 `tdsite`。这个名字全局唯一；如果提示已被占用，说明这个名字已经有人用了，需要换一个并同时改 systemd 里的 `TD_OSS_BUCKET`。
4. 地域选离云服务器近的，例如华东 1（杭州）。创建页给出的外网 Endpoint 填进 `TD_OSS_ENDPOINT`。杭州是 `https://oss-cn-hangzhou.aliyuncs.com`。
5. 存储类型选「标准存储」，读写权限选「私有」，阻止公共访问保持开启。
6. 创建完成后，点进该 Bucket 的「概览」，再核对一次名称和 Endpoint。

AccessKeyId 和 AccessKeySecret 属于一个只用来备份的 RAM 用户。Secret 只在创建成功那一页出现一次。

1. 打开 [RAM 用户](https://ram.console.aliyun.com/users)，创建用户。登录名称例如 `td-backup`。访问方式只勾选「使用永久 AccessKey 访问」，不要勾选控制台登录。
2. 创建完成的页面上，AccessKey ID 填 `TD_OSS_ACCESS_KEY_ID`，AccessKey Secret 填 `TD_OSS_ACCESS_KEY_SECRET`。立刻保存。以后 Secret 不能再查看，丢了就在该用户的「认证管理」里新建一对，并停用旧的。
3. 到 [权限策略](https://ram.console.aliyun.com/policies) 新建自定义策略，名称例如 `td-backup-oss`。策略只允许读写 Bucket `tdsite`：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:ListObjects"],
      "Resource": ["acs:oss:*:*:tdsite"]
    },
    {
      "Effect": "Allow",
      "Action": ["oss:GetObject", "oss:PutObject", "oss:DeleteObject"],
      "Resource": ["acs:oss:*:*:tdsite/*"]
    }
  ]
}
```

4. 回到 `td-backup` 这个用户，「权限」里新增授权，把 `td-backup-oss` 授给它。这样这对密钥只能读写这一个 Bucket。

把这三项和 Endpoint 写进第 4 节的 systemd，然后 `sudo systemctl daemon-reload && sudo systemctl restart td`。写好并重启之后，服务每次启动会先备份一份，然后按 `TD_BACKUP_INTERVAL` 重复。默认 86400 秒，也就是每天一次，并在 OSS 上保留最近 `TD_BACKUP_KEEP` 份（默认 14 份），更早的对象会删掉。设成 `TD_BACKUP_INTERVAL=0` 就只关自动备份，手动命令还能用。四项没配全时不会备份，网站照常开。

更新代码后要重新装依赖，否则没有 `oss2`：

```bash
cd /opt/td
.venv/bin/pip install -e .
sudo systemctl restart td
```

立刻打一份、或查看 OSS 上已有的包：

```bash
cd /opt/td
.venv/bin/python -m td_api.backup backup
.venv/bin/python -m td_api.backup list
```

迁到另一台机器时，新机器按第 1 到第 5 节装好程序和 Redis，systemd 里写同一套 OSS 变量。然后停服务、恢复、再启动。服务开着时去恢复，磁盘上的库会换掉，进程仍拿着旧连接，账是旧的，所以必须先停。

```bash
sudo systemctl stop td
cd /opt/td
.venv/bin/python -m td_api.backup restore --latest --force
sudo systemctl start td
```

新目录里还没有 `*.db` 时可以不加 `--force`。加了 `--force`，覆盖前的库先挪到 `/opt/td/data/users/.before-restore/`。要回到某一份，把 `list` 打印出的对象名填进去：

```bash
.venv/bin/python -m td_api.backup restore td-backups/20261128T111300123456+0800.tar.gz --force
```

包已经下载到本机、不需要再访问 OSS 时：

```bash
.venv/bin/python -m td_api.backup restore --file /tmp/backup.tar.gz --force
```

## 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `TD_REDIS` | `redis://127.0.0.1:6379/0` | 账号和会话。生产环境不要用 `memory` |
| `TD_DATA_DIR` | `data/users` | 每人一个 SQLite。生产环境写成绝对路径 |
| `TD_LEGACY` | `data/td.db` | 仅第一个用户还没有账本文件时复制这一份 |
| `TD_ADMINS` | 空 | 额外的管理员用户名，逗号分隔。不设时，1 号用户是管理员 |
| `TUSHARE_TOKEN` | 空 | 不设则 Tushare 在页面上显示为未配置 |
| `TD_QUOTES` | 代码里的默认源 | 逗号分隔，例如 `eastmoney,sina` |
| `TD_OSS_ENDPOINT` | 空 | 阿里云 OSS 外网地址。配全四项后默认每天自动备份 |
| `TD_OSS_BUCKET` | 空 | Bucket 名称。这台服务用 `tdsite` |
| `TD_OSS_ACCESS_KEY_ID` | 空 | RAM 用户的 AccessKey |
| `TD_OSS_ACCESS_KEY_SECRET` | 空 | 对应的 Secret |
| `TD_OSS_PREFIX` | `td-backups` | 对象键前缀 |
| `TD_BACKUP_INTERVAL` | 配好 OSS 时为 `86400` | 自动备份间隔，秒。`0` 关闭自动备份 |
| `TD_BACKUP_KEEP` | `14` | OSS 上保留的份数，更早的会删掉 |

## 出问题时看哪里

- 页面打不开：`sudo systemctl status td nginx`，以及安全组是否放了 80/443
- 打开是「前端还没构建」：在 `/opt/td/web` 执行 `npm run build`，再 `sudo systemctl restart td`
- 注册或登录失败：`redis-cli ping`，以及 `journalctl -u td -n 50 --no-pager` 里有没有「连不上 Redis」
- 行情失败、仓位现价不更新：在服务器上 `curl -I http://push2.eastmoney.com` 和 `curl -I https://hq.sinajs.cn`。超时就是这台机器出不去，或行情源暂时不可用。换源不会自动发生，页面上选的源失败就直接报错
- 出现 `Remote end closed connection without response`：多半是用公网 IP 访问了 HTTPS，而 Nginx 没有 `default_server`。按上面的默认站点配好后，裸 IP 会返回 403，域名访问保持 200。先看 `sudo tail -50 /var/log/nginx/error.log`，再用 `sudo nginx -T` 确认 443 上既有 `tdsite.cn` / `www.tdsite.cn`，也有 `default_server`。不要用 `return 444`
- 证书失败：先确认 `curl -I http://tdsite.cn` 能到 Nginx，再跑 certbot。域名还没解析到这台机器时，证书签不下来
- 自动备份失败：看 `journalctl -u td -n 50 --no-pager` 里的「OSS 备份失败」，以及 `/api/health` 的 `backup.last_error`。常见原因是 AccessKey、Bucket 或 Endpoint 填错，或这台机器访问不了 OSS 外网
