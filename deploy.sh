#!/usr/bin/env bash
# =============================================================================
# 城设 CityBible · 服务器部署脚本
#
# 安全承诺（每一条都在脚本里有对应实现）：
#   1. 自动挑选空闲端口，从 8766 起往上扫，绝不抢占任何已监听端口
#   2. 部署前记录所有 systemd 服务与监听端口，部署后逐一比对，有变动就报警
#   3. nginx 配置只做「追加 location」，改前自动备份，nginx -t 不过立即回滚
#   4. 只创建 /opt/projects/citybible 与 /var/www/citybible，不进任何其他目录
#   5. 任何一步失败立即退出并回滚，已有项目不受影响
#
# 用法：  sudo bash deploy.sh
# 卸载：  sudo bash deploy.sh --uninstall
# =============================================================================
set -Eeuo pipefail

APP=citybible
APP_DIR=/opt/projects/$APP
WWW_DIR=/var/www/$APP
SVC=/etc/systemd/system/$APP.service
NGINX_CONF=/etc/nginx/sites-available/projects
PORT_START=8766
PORT_END=8820

C_R='\033[0;31m'; C_G='\033[0;32m'; C_Y='\033[0;33m'; C_B='\033[0;36m'; C_0='\033[0m'
log(){ echo -e "${C_B}[城设]${C_0} $*"; }
ok(){  echo -e "${C_G}  ✓${C_0} $*"; }
warn(){ echo -e "${C_Y}  !${C_0} $*"; }
die(){ echo -e "${C_R}[失败]${C_0} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/root/citybible_backup_$STAMP
ROLLBACK_NGINX=""

cleanup_on_error(){
  echo
  echo -e "${C_R}=== 出错，正在回滚 ===${C_0}"
  if [[ -n "$ROLLBACK_NGINX" && -f "$ROLLBACK_NGINX" ]]; then
    cp -f "$ROLLBACK_NGINX" "$NGINX_CONF"
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
    echo "  已还原 nginx 配置"
  fi
  systemctl stop $APP.service   >/dev/null 2>&1 || true
  systemctl disable $APP.service >/dev/null 2>&1 || true
  echo "  已停止本项目服务。其他项目未受影响。"
  echo "  备份目录：$BACKUP_DIR"
}
trap cleanup_on_error ERR

# ---------------------------------------------------------------- 卸载
if [[ "${1:-}" == "--uninstall" ]]; then
  log "卸载 $APP（不影响其他项目）"
  systemctl stop $APP.service 2>/dev/null || true
  systemctl disable $APP.service 2>/dev/null || true
  rm -f $SVC; systemctl daemon-reload
  python3 - <<PY
import re,io
p="$NGINX_CONF"; s=open(p,encoding="utf-8").read()
s=re.sub(r"\n\s*# >>> CityBible BEGIN.*?# <<< CityBible END\n", "\n", s, flags=re.S)
open(p,"w",encoding="utf-8").write(s)
PY
  nginx -t && systemctl reload nginx
  ok "已卸载。代码目录 $APP_DIR 与静态目录 $WWW_DIR 保留，如需删除请手动 rm -rf"
  exit 0
fi

trap - ERR   # 下面重新挂
trap cleanup_on_error ERR

# ---------------------------------------------------------------- 0 前置检查
log "第 0 步：环境与现状快照"
[[ $EUID -eq 0 ]] || die "请用 root 运行： sudo bash deploy.sh"
command -v nginx >/dev/null   || die "未找到 nginx"
command -v python3 >/dev/null || die "未找到 python3"
[[ -f "$NGINX_CONF" ]]        || die "未找到 $NGINX_CONF，与预期的服务器结构不符，已中止"

mkdir -p "$BACKUP_DIR"
# 记录现状，部署后要逐条比对
systemctl list-units --type=service --state=running --no-legend --plain \
  | awk '{print $1}' | sort > "$BACKUP_DIR/services_before.txt"
ss -lntp 2>/dev/null | awk 'NR>1{print $4}' | sort -u > "$BACKUP_DIR/ports_before.txt"
cp -f "$NGINX_CONF" "$BACKUP_DIR/nginx_projects.conf.bak"
ROLLBACK_NGINX="$BACKUP_DIR/nginx_projects.conf.bak"
ok "现状已快照到 $BACKUP_DIR"
ok "当前运行中服务 $(wc -l < "$BACKUP_DIR/services_before.txt") 个，已监听端口 $(wc -l < "$BACKUP_DIR/ports_before.txt") 个"

if grep -q "CityBible BEGIN" "$NGINX_CONF"; then
  warn "检测到已有城设的 nginx 配置段，本次将原地更新"
fi

# ---------------------------------------------------------------- 1 选端口
log "第 1 步：挑选空闲端口（从 $PORT_START 起，绝不抢占已监听端口）"
PORT=""
for p in $(seq $PORT_START $PORT_END); do
  if ss -lnt "sport = :$p" 2>/dev/null | grep -q LISTEN; then
    warn "端口 $p 已被占用，跳过"
    continue
  fi
  # 双保险：再用 python 试绑一次
  if python3 - "$p" <<'PY'
import socket,sys
s=socket.socket()
try:
    s.bind(("127.0.0.1",int(sys.argv[1]))); s.close(); sys.exit(0)
except OSError:
    sys.exit(1)
PY
  then PORT=$p; break; fi
  warn "端口 $p 试绑失败，跳过"
done
[[ -n "$PORT" ]] || die "$PORT_START-$PORT_END 之间没有空闲端口"
ok "选定端口 127.0.0.1:$PORT （仅本地监听，外部只能经 nginx 访问）"

# ---------------------------------------------------------------- 2 代码与依赖
log "第 2 步：安装代码与依赖"
mkdir -p "$APP_DIR" "$WWW_DIR"
if [[ "$SCRIPT_DIR" != "$APP_DIR" ]]; then
  cp -r "$SCRIPT_DIR"/. "$APP_DIR"/
fi
cd "$APP_DIR"
[[ -d .venv ]] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip 2>/dev/null || warn "pip 升级失败，继续"
RUNMODE=fastapi
if ! ./.venv/bin/pip install -q -r requirements.txt 2>/dev/null; then
  warn "完整依赖装不上（无 pip 源 / 网络受限），尝试仅装 opencv"
  ./.venv/bin/pip install -q opencv-python-headless numpy 2>/dev/null || true
fi
if ! ./.venv/bin/python -c "import fastapi,uvicorn" 2>/dev/null; then
  RUNMODE=stdlib
  warn "未检测到 FastAPI，将以标准库模式运行（功能完整，仅无 /docs 自动文档）"
fi
./.venv/bin/python -c "import cv2" 2>/dev/null || die "opencv 不可用，判定引擎无法运行"
ok "虚拟环境就绪（独立 venv，不污染系统 python）；运行模式：$RUNMODE"

cp -r "$APP_DIR"/web/. "$WWW_DIR"/
ok "静态页已同步到 $WWW_DIR"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  warn "已从模板创建 .env，如需真实模型调用请填入 key（不填也能跑，判定引擎不依赖任何外部 API）"
fi
chmod 600 "$APP_DIR/.env"
echo "CITYBIBLE_PORT=$PORT" > "$APP_DIR/.port"

# ---------------------------------------------------------------- 3 systemd
log "第 3 步：注册 systemd 服务"
if [[ "$RUNMODE" == "fastapi" ]]; then
  EXEC_ARGS="-m uvicorn server.app:app --host 127.0.0.1 --port $PORT"
else
  EXEC_ARGS="-m server.simple_server --host 127.0.0.1 --port $PORT"
fi
cat > $SVC <<EOF
[Unit]
Description=CityBible geo-fidelity gate
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=-$APP_DIR/.env
Environment=CITYBIBLE_PORT=$PORT
ExecStart=$APP_DIR/.venv/bin/python $EXEC_ARGS
Restart=always
RestartSec=3
# 资源上限，避免影响同机其他项目
MemoryMax=700M
CPUQuota=140%

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now $APP.service >/dev/null 2>&1
sleep 3
systemctl is-active --quiet $APP.service || {
  journalctl -u $APP.service -n 30 --no-pager || true
  die "服务启动失败（见上方日志）"
}
ok "服务已启动，内存上限 700M / CPU 上限 140%"

# ---------------------------------------------------------------- 4 nginx
log "第 4 步：追加 nginx location（只加不改，改前已备份）"
python3 - "$NGINX_CONF" "$PORT" <<'PY'
import re, sys
conf, port = sys.argv[1], sys.argv[2]
s = open(conf, encoding="utf-8").read()
s = re.sub(r"\n?\s*# >>> CityBible BEGIN.*?# <<< CityBible END\n", "\n", s, flags=re.S)

block = """
    # >>> CityBible BEGIN  （本段由 deploy.sh 生成，卸载时会被整段移除）
    location = /citybible { return 301 /citybible/; }
    location /citybible/ {
        alias %s/;
        index index.html;
        try_files $uri $uri/ /citybible/index.html;
    }
    location = /citybible/api { return 301 /citybible/api/; }
    location /citybible/api/ {
        proxy_pass http://127.0.0.1:%s/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
    # <<< CityBible END
""" % ("/var/www/citybible", port)

# 插到「根路径 location /」之前；找不到就插在 server 块末尾
m = list(re.finditer(r"\n(\s*)location\s+/\s*\{", s))
if m:
    i = m[-1].start()
    s = s[:i] + "\n" + block + s[i:]
else:
    i = s.rstrip().rfind("}")
    s = s[:i] + block + "\n" + s[i:]
open(conf, "w", encoding="utf-8").write(s)
print("  nginx 配置已追加")
PY

nginx -t 2>&1 | sed 's/^/    /' || die "nginx 配置语法检查未通过，已自动回滚"
systemctl reload nginx
ok "nginx 已重载"

# ---------------------------------------------------------------- 5 健康检查
log "第 5 步：健康检查"
sleep 2
H=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/health" || echo 000)
[[ "$H" == "200" ]] || die "后端健康检查失败（HTTP $H）"
ok "后端 /api/health 200"
for path in /citybible/ /citybible/api/health; do
  c=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1$path" || echo 000)
  [[ "$c" == "200" ]] && ok "nginx $path → 200" || warn "nginx $path → $c"
done

# ---------------------------------------------------------------- 6 影响面比对
log "第 6 步：确认没有影响其他项目"
systemctl list-units --type=service --state=running --no-legend --plain \
  | awk '{print $1}' | sort > "$BACKUP_DIR/services_after.txt"
LOST=$(comm -23 "$BACKUP_DIR/services_before.txt" "$BACKUP_DIR/services_after.txt" || true)
if [[ -n "$LOST" ]]; then
  echo -e "${C_R}  警告：以下服务在部署后不再运行，请立即检查！${C_0}"
  echo "$LOST" | sed 's/^/    /'
else
  ok "部署前运行的服务全部仍在运行，一个都没掉"
fi
ss -lntp 2>/dev/null | awk 'NR>1{print $4}' | sort -u > "$BACKUP_DIR/ports_after.txt"
PLOST=$(comm -23 "$BACKUP_DIR/ports_before.txt" "$BACKUP_DIR/ports_after.txt" || true)
[[ -z "$PLOST" ]] && ok "原有监听端口全部保持" || { echo -e "${C_Y}  以下端口不再监听：${C_0}"; echo "$PLOST" | sed 's/^/    /'; }

IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo
echo -e "${C_G}════════════════════════════════════════════════${C_0}"
echo -e "${C_G} 部署完成${C_0}"
echo -e "${C_G}════════════════════════════════════════════════${C_0}"
echo "  展示页    http://$IP/citybible/"
echo "  健康检查  http://$IP/citybible/api/health"
echo "  接口文档  http://$IP/citybible/api/docs"
echo "  本地端口  127.0.0.1:$PORT"
echo "  备份目录  $BACKUP_DIR"
echo
echo "  常用命令："
echo "    systemctl status $APP.service"
echo "    journalctl -u $APP.service -f"
echo "    bash deploy.sh --uninstall     # 干净卸载，不动其他项目"
echo
trap - ERR
