#!/bin/bash
# Runs inside the test VM.
# Strategy:
#   1. Run install.sh from the uploaded local source (so it bootstraps deps).
#   2. After install, replace /opt/serverkit with the uploaded local working
#      tree (overlay), rebuild frontend, reinstall Python deps, restart.
#   3. Probe health endpoint and exit non-zero if anything failed.
#
# This way we test the EXACT local code, including uncommitted changes,
# instead of whatever is on origin/main.
set -u  # NB: not -e — we want to capture failures and still emit a report

SRC=/opt/serverkit-src
INSTALL_DIR=/opt/serverkit
LOG=/var/log/serverkit-test-install.log

log() { echo "[vm-install] $*" | tee -a "$LOG"; }
fail() { echo "[vm-install] FAIL: $*" | tee -a "$LOG"; exit 1; }

mkdir -p "$(dirname "$LOG")"
: > "$LOG"

[ -d "$SRC" ] || fail "source dir $SRC missing — multipass transfer broken"
[ -f "$SRC/install.sh" ] || fail "install.sh not found in source"

log "Step 1/4: running install.sh (this clones origin/main, installs deps)"
# install.sh clones from GitHub — we let it, then overlay our local code.
bash "$SRC/install.sh" >> "$LOG" 2>&1
INSTALL_RC=$?
log "install.sh exit=$INSTALL_RC"

if [ ! -d "$INSTALL_DIR" ]; then
  fail "install.sh did not create $INSTALL_DIR (rc=$INSTALL_RC)"
fi

log "Step 2/4: overlaying local working tree onto $INSTALL_DIR"
# Preserve .env / instance / nginx ssl from the install
rsync -a \
  --exclude='.env' \
  --exclude='backend/instance/' \
  --exclude='nginx/ssl/' \
  --exclude='backend/venv/' \
  --exclude='backend/.venv/' \
  --exclude='backend/.venv-wsl/' \
  --exclude='frontend/node_modules/' \
  --exclude='frontend/dist/' \
  --exclude='.git/' \
  "$SRC/" "$INSTALL_DIR/" >> "$LOG" 2>&1 || fail "rsync overlay failed"

log "Step 3/4: rebuild + restart with local code"
cd "$INSTALL_DIR" || fail "cd $INSTALL_DIR"

# Reinstall Python deps in case requirements.txt changed
if [ -d "$INSTALL_DIR/venv" ]; then
  "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" >> "$LOG" 2>&1 \
    || log "WARN: pip install had non-zero exit"
fi

# Rebuild frontend
cd "$INSTALL_DIR/frontend" || fail "cd frontend"
NODE_OPTIONS="--max-old-space-size=1024" npm run build >> "$LOG" 2>&1 \
  || fail "frontend build failed"

cd "$INSTALL_DIR" || true
docker compose build >> "$LOG" 2>&1 || log "WARN: docker compose build had non-zero exit"
docker compose up -d >> "$LOG" 2>&1 || log "WARN: docker compose up had non-zero exit"

systemctl restart serverkit >> "$LOG" 2>&1 || fail "systemctl restart serverkit failed"
systemctl restart nginx >> "$LOG" 2>&1 || log "WARN: nginx restart had non-zero exit"

log "Step 4/4: waiting for health endpoint"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:5000/api/v1/system/health > /dev/null 2>&1; then
    log "Backend healthy after ${i}s"
    echo "OK" > /tmp/serverkit-install-status
    exit 0
  fi
  sleep 1
done

log "Backend never became healthy"
systemctl status serverkit --no-pager >> "$LOG" 2>&1 || true
journalctl -u serverkit --no-pager -n 100 >> "$LOG" 2>&1 || true
echo "FAIL" > /tmp/serverkit-install-status
exit 1
