# Production Deployment Guide

This guide explains how to set up and manage the Stiflyt application in a production environment.

## Overview

The production environment is set up to:
- Run independently from the development environment
- Automatically pull code from GitHub
- Run as the `stiflyt` system user
- Use systemd for service management
- Support automated deployments via systemd timer

## Directory Structure

```
/opt/stiflyt/          # Production code directory (owned by stiflyt:stiflyt)
├── venv/              # Python virtual environment
├── backups/           # Deployment backups
├── deploy.log         # Deployment log
└── ...                # Application code
```

## Initial Setup

### 1. Clone Repository as stiflyt User

```bash
# Switch to stiflyt user (or use sudo)
sudo -u stiflyt bash

# Clone repository
cd /opt
git clone <your-github-repo-url> stiflyt
cd stiflyt

# Configure git (if needed)
git config user.name "Stiflyt Production"
git config user.email "stiflyt@example.com"
```

### 2. Install Dependencies

```bash
# As stiflyt user
cd /opt/stiflyt
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 3. Configure Environment

Create `.env` file in `/opt/stiflyt/` with production settings:

```bash
# As stiflyt user
cd /opt/stiflyt
cp .env.example .env
# Edit .env with production database credentials
```

### 4. Make Deployment Script Executable

```bash
chmod +x /opt/stiflyt/scripts/deploy.sh
```

### 5. Install Systemd Service

```bash
# Copy service files
sudo cp /opt/stiflyt/scripts/stiflyt.service /etc/systemd/system/
sudo cp /opt/stiflyt/scripts/stiflyt-deploy.service /etc/systemd/system/
sudo cp /opt/stiflyt/scripts/stiflyt-deploy.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start the service
sudo systemctl enable stiflyt.service
sudo systemctl start stiflyt.service

# Enable automated deployments (optional)
sudo systemctl enable stiflyt-deploy.timer
sudo systemctl start stiflyt-deploy.timer
```

## Manual Deployment

### Deploy as stiflyt User

```bash
sudo -u stiflyt /opt/stiflyt/scripts/deploy.sh
```

### Deploy with Custom Branch

```bash
sudo -u stiflyt bash -c 'cd /opt/stiflyt && GIT_BRANCH=develop scripts/deploy.sh'
```

## Service Management

### Start/Stop/Restart Service

```bash
sudo systemctl start stiflyt
sudo systemctl stop stiflyt
sudo systemctl restart stiflyt
```

### Check Service Status

```bash
sudo systemctl status stiflyt
```

### View Logs

```bash
# Systemd logs
sudo journalctl -u stiflyt -f

# Deployment logs
sudo -u stiflyt tail -f /opt/stiflyt/deploy.log
```

## Automated Deployments

The systemd timer runs deployments automatically:
- **Daily at 2:00 AM** (configurable in `stiflyt-deploy.timer`)
- **15 minutes after boot** (for testing)

### Manage Timer

```bash
# Check timer status
sudo systemctl status stiflyt-deploy.timer

# List timers
sudo systemctl list-timers stiflyt-deploy.timer

# Manually trigger deployment
sudo systemctl start stiflyt-deploy.service

# Disable automated deployments
sudo systemctl stop stiflyt-deploy.timer
sudo systemctl disable stiflyt-deploy.timer
```

## Git Configuration

### Fixing "dubious ownership" Error

If you need to run git commands as a different user (e.g., `otroan`), you have two options:

**Option 1: Use sudo (Recommended)**
```bash
sudo -u stiflyt git pull
```

**Option 2: Add safe.directory exception (for development/admin access)**
```bash
git config --global --add safe.directory /opt/stiflyt
```

**Note:** Option 2 allows git operations but files created will be owned by your user, not `stiflyt`. Always fix ownership after:
```bash
sudo chown -R stiflyt:stiflyt /opt/stiflyt
```

## Backup and Rollback

### Automatic Backups

The deployment script automatically creates backups in `/opt/stiflyt/backups/` before each deployment.

### Manual Rollback

```bash
# List backups
ls -la /opt/stiflyt/backups/

# Restore from backup
sudo -u stiflyt bash
cd /opt/stiflyt
rsync -a backups/backup-YYYYMMDD-HHMMSS-COMMIT/ ./
# Fix ownership if needed
chown -R stiflyt:stiflyt /opt/stiflyt
```

## Troubleshooting

### Service Won't Start

1. Check service status:
   ```bash
   sudo systemctl status stiflyt
   ```

2. Check logs:
   ```bash
   sudo journalctl -u stiflyt -n 50
   ```

3. Test manually:
   ```bash
   sudo -u stiflyt bash
   cd /opt/stiflyt
   source venv/bin/activate
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```

### Deployment Fails

1. Check deployment log:
   ```bash
   sudo -u stiflyt tail -f /opt/stiflyt/deploy.log
   ```

2. Check git status:
   ```bash
   sudo -u stiflyt bash
   cd /opt/stiflyt
   git status
   git log --oneline -5
   ```

3. Verify permissions:
   ```bash
   ls -la /opt/stiflyt
   # Should be owned by stiflyt:stiflyt
   ```

### Database Connection Issues

1. Verify database user exists:
   ```bash
   sudo -u postgres psql -c "\du stiflyt_reader"
   ```

2. Test connection:
   ```bash
   sudo -u stiflyt bash
   cd /opt/stiflyt
   source venv/bin/activate
   python -c "from services.database import get_db_connection; conn = get_db_connection(); print('OK'); conn.close()"
   ```

## Security Considerations

1. **File Ownership**: Always ensure `/opt/stiflyt` is owned by `stiflyt:stiflyt`
2. **Permissions**: The service runs with restricted permissions (see `stiflyt.service`)
3. **Environment Variables**: Store sensitive data in `.env` file (not in systemd service file)
4. **Git Credentials**: Use SSH keys or deploy tokens, not passwords
5. **Backups**: Regularly clean old backups to save disk space

## Maintenance

### Clean Old Backups

```bash
# Keep only last 10 backups
sudo -u stiflyt bash
cd /opt/stiflyt/backups
ls -t | tail -n +11 | xargs rm -rf
```

### Update Dependencies

The deployment script automatically updates dependencies. To manually update:

```bash
sudo -u stiflyt bash
cd /opt/stiflyt
source venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### Rotate Logs

Deployment logs are appended to `/opt/stiflyt/deploy.log`. To rotate:

```bash
sudo -u stiflyt bash
cd /opt/stiflyt
mv deploy.log deploy.log.old
touch deploy.log
```

