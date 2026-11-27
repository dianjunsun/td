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

必须先构建出 `web/dist`，再启动进程。`/assets` 在进程启动时挂载；先启动后构建，页面样式和脚本会 404，需要再重启一次。

如果要把现有账本带上云：

- 每个用户的账本是 `data/users/{用户号}.db`
- 登录账号和会话在 Redis
- `data/td.db` 只在第一个注册用户还没有 `data/users/1.db` 时复制一次

把本机的 `data/users/` 拷到服务器的 `/opt/td/data/users/`。Redis 里的用户也要一起迁，否则账本文件在、登录账号不在。本机 Redis 如果是按 README 起在 `data/redis`，把该目录里的 `appendonly.aof` 和 `dump.rdb` 拷到服务器的 `/var/lib/redis/`，然后 `sudo systemctl restart redis-server`。两边 Redis 不要同时写同一份文件。

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

在服务器上先确认本机已经起来：

```bash
curl -sS http://127.0.0.1:8765/api/health
```

## 5. 挂到域名

站点名用 `tdsite.cn`。A 记录要已经指向这台机器。

```bash
sudo tee /etc/nginx/sites-available/td >/dev/null <<'EOF'
server {
    listen 80;
    server_name tdsite.cn;

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

签发证书并让 Nginx 跳转到 HTTPS：

```bash
sudo certbot --nginx -d tdsite.cn
```

按提示填邮箱。完成后用浏览器打开 `https://tdsite.cn` 。证书到期前 certbot 会自动续期，可以用 `sudo certbot renew --dry-run` 看一眼。

页面路由在 `#` 后面，例如 `https://tdsite.cn/#positions`。Nginx 不用另做前端路由。

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

改过前端之后要重启。否则旧进程可能还没挂上新的静态文件。

## 8. 备份

停机前至少备份这两处：

- `/opt/td/data/users/`：每个用户的持仓、现金和出资
- Redis 数据目录，一般是 `/var/lib/redis/`：用户名、密码哈希和登录会话

```bash
sudo tar -C / -czf "$HOME/td-backup-$(date +%F).tar.gz" opt/td/data/users var/lib/redis
```

丢了 SQLite 就没有账。丢了 Redis 就登不进去，账本文件还在，但账号对不上。

## 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `TD_REDIS` | `redis://127.0.0.1:6379/0` | 账号和会话。生产环境不要用 `memory` |
| `TD_DATA_DIR` | `data/users` | 每人一个 SQLite。生产环境写成绝对路径 |
| `TD_LEGACY` | `data/td.db` | 仅第一个用户还没有账本文件时复制这一份 |
| `TD_ADMINS` | 空 | 额外的管理员用户名，逗号分隔。不设时，1 号用户是管理员 |
| `TUSHARE_TOKEN` | 空 | 不设则 Tushare 在页面上显示为未配置 |
| `TD_QUOTES` | 代码里的默认源 | 逗号分隔，例如 `eastmoney,sina` |

## 出问题时看哪里

- 页面打不开：`sudo systemctl status td nginx`，以及安全组是否放了 80/443
- 打开是「前端还没构建」：在 `/opt/td/web` 执行 `npm run build`，再 `sudo systemctl restart td`
- 注册或登录失败：`redis-cli ping`，以及 `journalctl -u td -n 50 --no-pager` 里有没有「连不上 Redis」
- 行情失败、仓位现价不更新：在服务器上 `curl -I http://push2.eastmoney.com` 和 `curl -I https://hq.sinajs.cn`。超时就是这台机器出不去，或行情源暂时不可用。换源不会自动发生，页面上选的源失败就直接报错
- 证书失败：先确认 `curl -I http://tdsite.cn` 能到 Nginx，再跑 certbot。域名还没解析到这台机器时，证书签不下来
