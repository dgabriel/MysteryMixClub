#!/bin/bash

# One-command installation for DigitalOcean $6/month droplet
# Usage: curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/MysteryMixClub/main/install-minimal.sh | bash

set -e

echo "🚀 Installing MysteryMixClub on minimal DigitalOcean droplet..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root (use: sudo su)"
    exit 1
fi

# Update system
echo "📦 Updating system packages..."
apt update && apt upgrade -y

# Install Docker
echo "🐳 Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
rm get-docker.sh

# Install Git
echo "🔧 Installing Git..."
apt install git -y

# Install Docker Compose V2 (as Docker plugin)
echo "🔧 Installing Docker Compose V2..."
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Verify installation
docker compose version

# Enable swap (CRITICAL for 1GB RAM)
echo "💾 Enabling 2GB swap..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Get server IP
SERVER_IP=$(curl -s ifconfig.me)

# Create app directory
echo "📁 Setting up application directory..."
mkdir -p /opt/mysterymixclub
cd /opt/mysterymixclub

# Prompt for GitHub repo
read -p "Enter your GitHub username: " GITHUB_USER
REPO_URL="https://github.com/${GITHUB_USER}/MysteryMixClub.git"

echo "📥 Cloning repository from $REPO_URL..."
git clone $REPO_URL .

# Generate environment file
echo "🔐 Generating secure environment configuration..."
cat > .env.production << ENVEOF
DATABASE_URL=mysql+pymysql://mysterymix:$(openssl rand -base64 24 | tr -d '\n')@db:3306/mysterymixclub
MYSQL_ROOT_PASSWORD=$(openssl rand -base64 24 | tr -d '\n')
MYSQL_DATABASE=mysterymixclub
MYSQL_USER=mysterymix
MYSQL_PASSWORD=$(openssl rand -base64 24 | tr -d '\n')
SECRET_KEY=$(openssl rand -hex 32)
FRONTEND_URL=http://${SERVER_IP}
VITE_API_URL=http://${SERVER_IP}/api/v1
ENVIRONMENT=production
ENVEOF

echo "✅ Environment file created"

# Configure firewall
echo "🔥 Configuring firewall..."
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
echo "y" | ufw enable

# Deploy application
echo "🚀 Deploying application..."
chmod +x deploy.sh
./deploy.sh production

echo ""
echo "✅ Installation complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 MysteryMixClub is now running!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 Access your application at: http://${SERVER_IP}"
echo ""
echo "📊 Useful commands:"
echo "  Monitor memory:  watch -n 2 free -m"
echo "  View logs:       docker-compose -f docker-compose.prod.yml logs -f"
echo "  Restart:         docker-compose -f docker-compose.prod.yml restart"
echo "  Check status:    docker-compose -f docker-compose.prod.yml ps"
echo ""
echo "📝 Environment file location: /opt/mysterymixclub/.env.production"
echo ""
echo "💡 Next steps:"
echo "  1. Visit http://${SERVER_IP} to test"
echo "  2. Configure domain name (optional)"
echo "  3. Set up SSL with Let's Encrypt (see DEPLOYMENT.md)"
echo "  4. Set up backups"
echo ""
