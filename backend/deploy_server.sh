#!/usr/bin/env bash
# CSBOT 服务器一键部署脚本（systemd + 可选 Nginx HTTPS 反代，Flask + Gunicorn 版）
# 用法：
#   sudo bash deploy_server.sh [--user csbot] [--py python3] [--domain api.example.com] [--no-api] [--no-nginx]
# 说明：
#   - 不带 --domain 则不安装/配置 Nginx，仅本机 127.0.0.1:5000 可访问（更安全）
#   - 如无 api.py 或不想启用 API，传 --no-api

set -euo pipefail

############### 可调参数（也可通过命令行传参覆盖） ################
SERVICE_USER="csbot"
SERVICE_GROUP="csbot"
PYBIN="python3"
ENABLE_API=1
ENABLE_NGINX=1
DOMAIN=""
API_PORT=5000
WORKERS=2
###################################################################

# 颜色
BLUE="\033[0;34m"; GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
info(){ echo -e "${BLUE}[INFO]${NC} $*"; }
ok(){ echo -e "${GREEN}[OK]${NC} $*"; }
warn(){ echo -e "${YELLOW}[WARN]${NC} $*"; }
err(){ echo -e "${RED}[ERR]${NC} $*"; }

# 解析参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) SERVICE_USER="$2"; SERVICE_GROUP="$2"; shift 2;;
    --py) PYBIN="$2"; shift 2;;
    --domain) DOMAIN="$2"; ENABLE_NGINX=1; shift 2;;
    --no-api) ENABLE_API=0; shift 1;;
    --no-nginx) ENABLE_NGINX=0; DOMAIN=""; shift 1;;
    *) warn "未知参数：$1"; shift 1;;
  esac
done

# 需要 root
if [[ $EUID -ne 0 ]]; then
  err "请用 sudo 运行此脚本"; exit 1
fi

# 目录：以脚本所在目录为项目根
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR"

info "项目目录：$SCRIPT_DIR"
[[ -f "$SCRIPT_DIR/auto_run.py" ]] || { err "未找到 auto_run.py，请在项目根目录执行"; exit 1; }

if [[ "$ENABLE_API" -eq 1 ]]; then
  if [[ ! -f "$SCRIPT_DIR/api.py" ]]; then
    warn "未检测到 api.py（将仍创建服务，但可能无法启动）。如果无需 API，可加 --no-api"
  fi
fi

# 创建系统用户
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  info "创建系统用户：$SERVICE_USER"
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
else
  info "系统用户已存在：$SERVICE_USER"
fi
chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$SCRIPT_DIR"

# Python 版本检查
if ! command -v "$PYBIN" >/dev/null 2>&1; then
  info "安装 Python（$PYBIN）与依赖"
  apt-get update
  apt-get install -y python3 python3-venv python3-pip
  PYBIN="python3"
fi

# 虚拟环境
if [[ ! -d "$SCRIPT_DIR/venv" ]]; then
  info "创建虚拟环境 venv"
  sudo -u "$SERVICE_USER" "$PYBIN" -m venv "$SCRIPT_DIR/venv"
fi

# 升级 pip & 装依赖
V_PY="$SCRIPT_DIR/venv/bin/python"
PIP_UPGRADE=''"$V_PY"' -m pip install --upgrade pip'
REQ_INSTALL=''"$V_PY"' -m pip install -r requirements.txt'
FAST_DEPS=''"$V_PY"' -m pip install gunicorn flask flask-cors pandas numpy'
sudo -u "$SERVICE_USER" bash -lc "$PIP_UPGRADE"
if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
  info "安装 requirements.txt 依赖"
  sudo -u "$SERVICE_USER" bash -lc "$REQ_INSTALL" || true
else
  info "未发现 requirements.txt，将安装最小依赖（Flask + Gunicorn 等）"
  sudo -u "$SERVICE_USER" bash -lc "$FAST_DEPS" || true
fi

# .env
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  info "创建 .env（占位，后续自行填入密钥）"
  cat > "$SCRIPT_DIR/.env" <<'ENVV'
# 示例：
# API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxx
# OTHER_KEY=value
ENVV
fi
chown "$SERVICE_USER":"$SERVICE_GROUP" "$SCRIPT_DIR/.env"
chmod 600 "$SCRIPT_DIR/.env"

# systemd：auto_run
info "创建 systemd 服务：csbot-autoupdater.service"
cat > /etc/systemd/system/csbot-autoupdater.service <<UNIT
[Unit]
Description=CSBOT Auto Database Updater (build + model hourly)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=$SCRIPT_DIR/.env
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/auto_run.py --immediate --daemon
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNIT

# systemd：API（Flask + Gunicorn）
if [[ "$ENABLE_API" -eq 1 ]]; then
  info "创建 systemd 服务：csbot-api.service（127.0.0.1:${API_PORT}）"
  cat > /etc/systemd/system/csbot-api.service <<UNIT
[Unit]
Description=CSBOT API (Flask + Gunicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=$SCRIPT_DIR/.env
ExecStart=$SCRIPT_DIR/venv/bin/gunicorn -w $WORKERS -b 127.0.0.1:$API_PORT api:app
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNIT
fi

# 重新加载 + 启用服务
info "应用 systemd 配置并启动服务"
systemctl daemon-reload
systemctl enable --now csbot-autoupdater.service
if [[ "$ENABLE_API" -eq 1 ]]; then
  systemctl enable --now csbot-api.service
fi

# UFW 基础规则（可选）
if command -v ufw >/dev/null 2>&1; then
  info "配置 UFW（基础）"
  ufw allow OpenSSH >/dev/null 2>&1 || true
  if [[ "$ENABLE_API" -eq 1 && "$ENABLE_NGINX" -eq 0 ]]; then
    warn "未启用 Nginx/域名，本机端口 $API_PORT 默认不开放公网（推荐）"
    # 如需临时开放： ufw allow ${API_PORT}/tcp
  fi
else
  warn "未检测到 ufw（可忽略或自行配置防火墙）"
fi

# Nginx + HTTPS（如指定域名）
if [[ "$ENABLE_API" -eq 1 && "$ENABLE_NGINX" -eq 1 && -n "$DOMAIN" ]]; then
  info "安装并配置 Nginx 反代（域名：$DOMAIN）"
  apt-get update
  apt-get install -y nginx
  cat > "/etc/nginx/sites-available/csbot_api.conf" <<NGX
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$API_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGX
  ln -sf "/etc/nginx/sites-available/csbot_api.conf" "/etc/nginx/sites-enabled/csbot_api.conf"
  nginx -t && systemctl restart nginx

  # HTTPS（Let’s Encrypt）
  if ! command -v certbot >/dev/null 2>&1; then
    info "安装 certbot"
    snap install core && snap refresh core
    snap install --classic certbot
    ln -sf /snap/bin/certbot /usr/bin/certbot
  fi
  info "申请 HTTPS 证书（请确保域名已指向本机）"
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@"$DOMAIN" || warn "证书申请失败，请稍后手动执行：certbot --nginx -d $DOMAIN"

  # 防火墙端口
  if command -v ufw >/dev/null 2>&1; then
    ufw allow 80,443/tcp || true
    ufw deny ${API_PORT}/tcp || true   # 关闭直连 gunicorn 端口
  fi
fi

# 状态展示
echo
ok "部署完成"
echo -e "服务状态："
systemctl --no-pager --full status csbot-autoupdater.service | sed -n '1,12p' || true
if [[ "$ENABLE_API" -eq 1 ]]; then
  systemctl --no-pager --full status csbot-api.service | sed -n '1,12p' || true
fi

# 简易管理提示
echo
echo -e "${BLUE}常用命令：${NC}
  查看日志： journalctl -u csbot-autoupdater -f
  重启任务： systemctl restart csbot-autoupdater
  停止任务： systemctl stop csbot-autoupdater
"
if [[ "$ENABLE_API" -eq 1 ]]; then
  echo -e "${BLUE}API 调试：${NC}
  本机回环： curl -s http://127.0.0.1:${API_PORT}/status || true
  （如配置了域名）浏览： https://${DOMAIN}/status
"
fi

# 提醒
echo -e "${YELLOW}提醒：${NC}
- 请编辑 $SCRIPT_DIR/.env 填入实际 API_TOKEN 等敏感配置（权限 600 已设置）。
- API 仅监听 127.0.0.1:${API_PORT}，如需公网访问，请使用 Nginx & HTTPS（--domain 已自动配置）。
- 修改 auto_run.py / api.py 后： systemctl restart 对应服务即可生效。
"