# Quick Production Setup

## Initial Setup (One-time)

```bash
# 1. Clone repository as stiflyt user
sudo -u stiflyt bash
cd /opt
git clone <your-repo-url> stiflyt
cd stiflyt

# 2. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e .

# 3. Configure environment
cp .env.example .env
# Edit .env with production settings

# 4. Make deploy script executable
chmod +x scripts/deploy.sh
exit  # Exit stiflyt user shell

# 5. Install systemd services
sudo cp scripts/stiflyt.service /etc/systemd/system/
sudo cp scripts/stiflyt-deploy.service /etc/systemd/system/
sudo cp scripts/stiflyt-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload

# 6. Enable and start services
sudo systemctl enable stiflyt.service
sudo systemctl start stiflyt.service

# 7. (Optional) Enable automated deployments
sudo systemctl enable stiflyt-deploy.timer
sudo systemctl start stiflyt-deploy.timer
```

## Daily Operations

### Manual Deployment
```bash
sudo -u stiflyt /opt/stiflyt/scripts/deploy.sh
```

### Check Service Status
```bash
sudo systemctl status stiflyt
```

### View Logs
```bash
sudo journalctl -u stiflyt -f
```

### Restart Service
```bash
sudo systemctl restart stiflyt
```

## Git Operations

**Always use sudo -u stiflyt for git operations:**
```bash
sudo -u stiflyt git pull
sudo -u stiflyt git status
sudo -u stiflyt git log
```

This ensures files remain owned by `stiflyt:stiflyt`.

