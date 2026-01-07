#!/bin/bash
# Production deployment script for Stiflyt
# This script should be run as the stiflyt user or via sudo -u stiflyt

set -e  # Exit on error
set -u  # Exit on undefined variable

# Configuration
PROD_DIR="/opt/stiflyt"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-main}"
VENV_DIR="${PROD_DIR}/venv"
LOG_FILE="${PROD_DIR}/deploy.log"
BACKUP_DIR="${PROD_DIR}/backups"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_success() {
    log "${GREEN}✓${NC} $1"
}

log_error() {
    log "${RED}✗${NC} $1"
}

log_warning() {
    log "${YELLOW}⚠${NC} $1"
}

# Check if running as correct user
if [ "$(whoami)" != "stiflyt" ]; then
    log_error "This script must be run as user 'stiflyt'"
    log "Usage: sudo -u stiflyt $0"
    exit 1
fi

# Check if production directory exists
if [ ! -d "$PROD_DIR" ]; then
    log_error "Production directory $PROD_DIR does not exist"
    exit 1
fi

cd "$PROD_DIR"

# Create backup directory
mkdir -p "$BACKUP_DIR"

log "Starting deployment to $PROD_DIR"
log "Git remote: $GIT_REMOTE, branch: $GIT_BRANCH"

# Backup current version
CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BACKUP_NAME="backup-$(date +%Y%m%d-%H%M%S)-${CURRENT_COMMIT}"
log "Creating backup: $BACKUP_NAME"

# Create backup (excluding venv and large directories)
mkdir -p "${BACKUP_DIR}/${BACKUP_NAME}"
rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.git' --exclude='backups' \
    "$PROD_DIR/" "${BACKUP_DIR}/${BACKUP_NAME}/" || log_warning "Backup creation had issues"

# Check git authentication
log "Checking git authentication..."
if ! git ls-remote "$GIT_REMOTE" "$GIT_BRANCH" &>/dev/null; then
    log_error "Cannot access git remote $GIT_REMOTE"
    log_error "This usually means SSH keys are not set up for the stiflyt user"
    log_error "See scripts/GIT_AUTHENTICATION.md for setup instructions"
    exit 1
fi

# Fetch latest changes
log "Fetching latest changes from $GIT_REMOTE..."
git fetch "$GIT_REMOTE" "$GIT_BRANCH" || {
    log_error "Failed to fetch from $GIT_REMOTE"
    log_error "Check git authentication and network connectivity"
    exit 1
}

# Check if there are updates
LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse "${GIT_REMOTE}/${GIT_BRANCH}")

if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
    log "Already up to date (commit: $LOCAL_COMMIT)"
    exit 0
fi

log "Updating from $LOCAL_COMMIT to $REMOTE_COMMIT"

# Pull changes
log "Pulling changes..."
git pull "$GIT_REMOTE" "$GIT_BRANCH" || {
    log_error "Failed to pull changes"
    exit 1
}

# Update virtual environment if needed
if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

log "Updating dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet
pip install -e . --quiet || {
    log_error "Failed to install dependencies"
    exit 1
}

# Run any pre-deployment checks
if [ -f "scripts/pre_deploy.sh" ]; then
    log "Running pre-deployment checks..."
    bash scripts/pre_deploy.sh || {
        log_error "Pre-deployment checks failed"
        exit 1
    }
fi

log_success "Deployment completed successfully"
log "New commit: $(git rev-parse --short HEAD)"

# Note: Service restart should be handled by systemd or separately
# to avoid conflicts with the deployment script
log "Note: Restart the service manually or it will restart automatically if using systemd"

exit 0

