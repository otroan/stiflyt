# Git Authentication Setup for Production

The `stiflyt` user needs authentication to pull code from GitHub.

## ⭐ Option 1: Deploy Key (Recommended for Production)

**This is the most secure option** - it only grants access to a single repository and can be read-only.

### Step 1: Generate Deploy Key

```bash
# Switch to stiflyt user
sudo -u stiflyt bash

# Generate deploy key
ssh-keygen -t ed25519 -C "stiflyt-deploy-key" -f ~/.ssh/stiflyt_deploy_key

# Or use RSA if ed25519 is not available
ssh-keygen -t rsa -b 4096 -C "stiflyt-deploy-key" -f ~/.ssh/stiflyt_deploy_key

# Don't set a passphrase (press Enter twice)
```

### Step 2: Add Deploy Key to GitHub Repository

1. Display the public key:
   ```bash
   cat ~/.ssh/stiflyt_deploy_key.pub
   ```

2. Go to your GitHub repository → **Settings** → **Deploy keys**
3. Click **"Add deploy key"**
4. Paste the public key
5. **Title**: `stiflyt-production` (or similar)
6. **⚠️ IMPORTANT: Uncheck "Allow write access"** (read-only is safer for production)
7. Click **"Add key"**

### Step 3: Configure SSH to Use Deploy Key

```bash
# As stiflyt user
cat >> ~/.ssh/config << 'EOF'
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/stiflyt_deploy_key
    IdentitiesOnly yes
EOF

chmod 600 ~/.ssh/config
```

### Step 4: Verify Repository URL

```bash
# As stiflyt user
cd /opt/stiflyt
git remote -v

# If it shows HTTPS, change to SSH:
git remote set-url origin git@github.com:username/repository.git
```

### Step 5: Test Connection

```bash
# As stiflyt user
ssh -T git@github.com
# Should see: "Hi username/repository! You've successfully authenticated..."
```

**Note:** The message will show your repository name, not your username. This is normal for deploy keys.

## Option 2: HTTPS with Personal Access Token

Use this if you prefer HTTPS over SSH, or if SSH is not available.

### Step 1: Create GitHub Personal Access Token

1. Go to GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. Click **"Generate new token (classic)"**
3. **Note**: `stiflyt-production`
4. **Expiration**: Set appropriate expiration (or no expiration for production)
5. Select scope: **`repo`** (full control of private repositories)
6. Click **"Generate token"**
7. **Copy the token immediately** (you won't see it again!)

### Step 2: Configure Git to Use Token

```bash
# Switch to stiflyt user
sudo -u stiflyt bash
cd /opt/stiflyt

# Set remote to HTTPS (if not already)
git remote set-url origin https://github.com/username/repository.git

# Configure git credential helper
git config --global credential.helper store

# Test by pulling (will prompt for credentials)
git pull
# Username: your-github-username
# Password: paste-your-token-here (NOT your GitHub password!)
```

### Step 3: Store Credentials Securely

The credentials will be stored in `~stiflyt/.git-credentials`. Make sure it's secure:

```bash
chmod 600 ~stiflyt/.git-credentials
```

## Option 3: SSH Key on GitHub Account (Less Secure)

**⚠️ Only use this if you need access to multiple repositories.** For single-repo production deployments, use Deploy Keys (Option 1) instead.

### Step 1: Generate SSH Key for stiflyt User

```bash
# Switch to stiflyt user
sudo -u stiflyt bash

# Generate SSH key
ssh-keygen -t ed25519 -C "stiflyt-production" -f ~/.ssh/id_ed25519

# Or use RSA if ed25519 is not available
ssh-keygen -t rsa -b 4096 -C "stiflyt-production" -f ~/.ssh/id_rsa

# Don't set a passphrase (or use a secure passphrase and configure ssh-agent)
# Press Enter twice to skip passphrase
```

### Step 2: Add SSH Key to GitHub Account

```bash
# Display the public key
cat ~/.ssh/id_ed25519.pub
# Or if using RSA:
# cat ~/.ssh/id_rsa.pub
```

1. Copy the output
2. Go to GitHub → **Settings** → **SSH and GPG keys**
3. Click **"New SSH key"**
4. **Title**: `stiflyt-production`
5. Paste the key
6. Click **"Add SSH key"**

### Step 3: Test Connection

```bash
# As stiflyt user
ssh -T git@github.com
# Should see: "Hi username! You've successfully authenticated..."
```

### Step 4: Verify Repository URL

```bash
# As stiflyt user
cd /opt/stiflyt
git remote -v

# If it shows HTTPS, change to SSH:
git remote set-url origin git@github.com:username/repository.git
```

## Verify Setup

After setting up authentication, test the deployment:

```bash
sudo -u stiflyt /opt/stiflyt/scripts/deploy.sh
```

Or use the check script:

```bash
sudo -u stiflyt /opt/stiflyt/scripts/check_git_auth.sh
```

## Troubleshooting

### "Permission denied (publickey)"

- Check if SSH key exists: `sudo -u stiflyt ls -la ~stiflyt/.ssh/`
- Test SSH connection: `sudo -u stiflyt ssh -T git@github.com`
- Verify key is added to GitHub (deploy key or account)
- Check SSH config: `sudo -u stiflyt cat ~stiflyt/.ssh/config`
- For deploy keys, verify it's added to the **repository**, not your account

### "Could not read from remote repository"

- Verify repository URL: `sudo -u stiflyt bash -c "cd /opt/stiflyt && git remote -v"`
- Check if repository exists and is accessible
- Verify authentication method matches remote URL (SSH vs HTTPS)
- For deploy keys, ensure the key is added to the correct repository

### HTTPS Authentication Issues

- Check stored credentials: `sudo -u stiflyt cat ~stiflyt/.git-credentials`
- Re-authenticate: `sudo -u stiflyt bash -c "cd /opt/stiflyt && git pull"`
- Verify token hasn't expired

### Deploy Key Not Working

- Ensure deploy key is added to the **repository** (Settings → Deploy keys), not your account
- Check SSH config points to the correct key file
- Verify the repository URL uses SSH format: `git@github.com:user/repo.git`

## Security Best Practices

1. **✅ Use Deploy Keys** for production (most secure, read-only access)
2. **❌ Don't use personal SSH keys** in production
3. **🔄 Rotate keys regularly** (every 6-12 months)
4. **🔑 Use separate keys** for different environments (dev, staging, prod)
5. **👀 Monitor access** in GitHub repository settings
6. **🔒 Use read-only deploy keys** when write access isn't needed
7. **📝 Document which keys are used where**

## Comparison

| Method | Security | Scope | Best For |
|--------|----------|-------|----------|
| **Deploy Key** | ⭐⭐⭐⭐⭐ | Single repo | Production deployments |
| **Personal Access Token** | ⭐⭐⭐⭐ | All repos (with token scope) | CI/CD, automation |
| **SSH Key on Account** | ⭐⭐⭐ | All repos | Development, multiple repos |
