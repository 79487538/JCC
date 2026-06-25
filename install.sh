#!/bin/bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/<repo>/JCC.git}"
APP_DIR="${APP_DIR:-JCC}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"

on_error() {
  local exit_code=$?
  local line_no=$1
  echo "Install failed at line ${line_no}, exit code ${exit_code}."
  exit "${exit_code}"
}

trap 'on_error $LINENO' ERR

echo "Preparing server environment..."
apt update
apt install python3 python3-pip git curl -y

echo "Cloning project from GitHub..."
if [ -d "${APP_DIR}" ]; then
  echo "Directory ${APP_DIR} already exists, pulling latest code..."
  cd "${APP_DIR}"
  git pull
else
  git clone "${REPO_URL}" "${APP_DIR}"
  cd "${APP_DIR}"
fi

echo "Installing backend dependencies..."
pip3 install -r requirements.txt

echo "Creating runtime directories..."
mkdir -p logs

echo "Starting JCC AI backend in production mode..."
chmod +x start.sh
nohup bash start.sh > logs/app.log 2>&1 &

echo "Waiting for service health check..."
for i in {1..20}; do
  if curl -fsS "${HEALTH_URL}" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    echo "JCC AI Server Deployed Successfully"
    exit 0
  fi
  sleep 2
done

echo "Health check failed: ${HEALTH_URL}"
echo "Last logs:"
tail -n 50 logs/app.log || true
exit 1
