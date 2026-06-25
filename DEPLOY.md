# JCC AI Assistant Production Deployment

## 1. Server Requirements

- Linux server, Ubuntu 20.04+ recommended
- Python 3.10+
- Tesseract OCR binary installed if `/ocr/image` is used
- Open TCP port `8000` or the port configured in `.env`

## 2. Install Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv tesseract-ocr tesseract-ocr-chi-sim
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure Environment

Create `.env` from `.env.example` and edit the server address:

```bash
cp .env.example .env
nano .env
```

Example:

```env
API_BASE_URL=http://your-server-ip:8000
AI_PROVIDER=deepseek
ENABLE_AI=false
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

Do not put API keys in client files. Keep keys only as server environment variables.

## 4. Start Backend

Development or direct start:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Production script:

```bash
chmod +x start.sh
./start.sh
```

Background production run:

```bash
nohup ./start.sh > app.log 2>&1 &
```

The backend `__main__` startup uses `config.SERVER_HOST` and `config.SERVER_PORT`.

## 5. Open Firewall Port

Ubuntu UFW:

```bash
sudo ufw allow 8000/tcp
sudo ufw reload
sudo ufw status
```

Cloud servers may also require opening port `8000` in the provider security group.

After opening the port, verify from another machine:

```bash
curl http://your-server-ip:8000/health
```

## 6. Logs

Foreground run:

```bash
./start.sh 2>&1 | tee backend.log
```

Application request/error logs:

```bash
tail -f logs/app.log
```

Nohup logs:

```bash
tail -f app.log
```

Systemd example:

```bash
journalctl -u jcc-ai -f
```

## 7. Build Electron Client

From the Electron client directory:

```bash
cd electron-client
npm install
npm run build
npm run dist
```

The Windows installer is generated at:

```text
dist/JCC-AI-Setup.exe
```

## 8. User Flow

1. Install and start `JCC AI Assistant`
2. Client reads `API_BASE_URL` from system environment or project `.env`
3. Client connects to the deployed backend
4. OCR screenshot flow extracts game state
5. Backend analyzes the game state
6. Client displays stage, strength, strategy, priority, score, and recommendation
