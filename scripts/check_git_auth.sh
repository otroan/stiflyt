#!/bin/bash
# Quick script to check git authentication for stiflyt user

echo "Checking git authentication for stiflyt user..."
echo ""

# Check if running as stiflyt
if [ "$(whoami)" != "stiflyt" ]; then
    echo "⚠ This script should be run as stiflyt user"
    echo "Run: sudo -u stiflyt $0"
    exit 1
fi

cd /opt/stiflyt 2>/dev/null || {
    echo "✗ /opt/stiflyt does not exist"
    exit 1
}

echo "1. Checking SSH keys..."
if [ -f ~/.ssh/id_ed25519.pub ] || [ -f ~/.ssh/id_rsa.pub ] || [ -f ~/.ssh/stiflyt_deploy_key.pub ]; then
    echo "   ✓ SSH keys found"
    if [ -f ~/.ssh/id_ed25519.pub ]; then
        echo "   - id_ed25519.pub exists"
    fi
    if [ -f ~/.ssh/id_rsa.pub ]; then
        echo "   - id_rsa.pub exists"
    fi
    if [ -f ~/.ssh/stiflyt_deploy_key.pub ]; then
        echo "   - stiflyt_deploy_key.pub exists (deploy key)"
    fi
else
    echo "   ✗ No SSH keys found"
    echo "   See scripts/GIT_AUTHENTICATION.md for setup instructions"
fi

echo ""
echo "2. Testing SSH connection to GitHub..."
if ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo "   ✓ SSH authentication successful"
else
    echo "   ✗ SSH authentication failed"
    ssh -T git@github.com 2>&1 | head -3
fi

echo ""
echo "3. Checking git remote configuration..."
REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "not configured")
echo "   Remote URL: $REMOTE_URL"

if echo "$REMOTE_URL" | grep -q "^git@"; then
    echo "   ✓ Using SSH (git@github.com)"
elif echo "$REMOTE_URL" | grep -q "^https://"; then
    echo "   ⚠ Using HTTPS - check if credentials are configured"
    if [ -f ~/.git-credentials ]; then
        echo "   ✓ Git credentials file exists"
    else
        echo "   ✗ No git credentials file found"
    fi
else
    echo "   ✗ Remote not properly configured"
fi

echo ""
echo "4. Testing git fetch..."
if git fetch origin --dry-run 2>&1 | grep -q "fatal\|error\|denied"; then
    echo "   ✗ Git fetch failed"
    git fetch origin --dry-run 2>&1 | head -3
else
    echo "   ✓ Git fetch test successful"
fi

echo ""
echo "Summary:"
if git ls-remote origin HEAD &>/dev/null; then
    echo "✓ Git authentication is working!"
else
    echo "✗ Git authentication is NOT working"
    echo ""
    echo "Next steps:"
    echo "1. Read scripts/GIT_AUTHENTICATION.md"
    echo "2. Set up SSH keys or HTTPS token"
    echo "3. Run this script again to verify"
fi

