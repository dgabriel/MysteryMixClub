# MysteryMixClub - DigitalOcean Deployment Guide

## Overview

This guide covers deploying MysteryMixClub to DigitalOcean using Docker Compose on a Droplet.

## Prerequisites

- DigitalOcean account
- Domain name (optional but recommended)
- SSH key configured
- GitHub repository with latest code

## Estimated Costs

- **Minimal Droplet**: $6/month (1GB RAM, 1 vCPU) - See DEPLOYMENT-MINIMAL.md
- **Basic Droplet**: $12/month (2GB RAM, 1 vCPU)
- **Recommended Droplet**: $18/month (2GB RAM, 2 vCPU)
- **Domain**: ~$12/year (if purchasing)
- **Total**: ~$6-30/month depending on needs

💡 **Budget Option**: Use the $6/month droplet for MVP/testing. See [DEPLOYMENT-MINIMAL.md](./DEPLOYMENT-MINIMAL.md) for optimized setup.

## Step 1: Create DigitalOcean Droplet

### Via DigitalOcean Dashboard:

1. Go to https://cloud.digitalocean.com/droplets
2. Click "Create Droplet"
3. **Choose Region**: Select closest to your users
4. **Choose Image**: Ubuntu 22.04 LTS
5. **Choose Size**:
   - Minimum: Basic - $12/month (2GB RAM, 1 vCPU, 50GB SSD)
   - Recommended: Basic - $18/month (2GB RAM, 2 vCPU, 60GB SSD)
6. **Authentication**: Add your SSH key
7. **Hostname**: mysterymixclub-prod
8. Click "Create Droplet"

### Via DigitalOcean CLI (doctl):

```bash
# Install doctl
brew install doctl

# Authenticate
doctl auth init

# Create droplet
doctl compute droplet create mysterymixclub-prod \
  --region nyc3 \
  --size s-2vcpu-2gb \
  --image ubuntu-22-04-x64 \
  --ssh-keys YOUR_SSH_KEY_ID
```

## Step 2: Configure Domain (Optional)

If you have a domain:

1. Go to DigitalOcean > Networking > Domains
2. Add your domain
3. Create A record pointing to your droplet's IP:
   - Hostname: `@` → Droplet IP
   - Hostname: `www` → Droplet IP

Or update your domain registrar's DNS:
- A record: `yourdomain.com` → `YOUR_DROPLET_IP`
- A record: `www.yourdomain.com` → `YOUR_DROPLET_IP`

## Step 3: Connect to Droplet and Install Dependencies

```bash
# SSH into your droplet
ssh root@YOUR_DROPLET_IP

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt install docker-compose -y

# Install Git
apt install git -y

# Create application directory
mkdir -p /opt/mysterymixclub
cd /opt/mysterymixclub
```

## Step 4: Clone Repository

```bash
# Clone your repository
git clone https://github.com/YOUR_USERNAME/MysteryMixClub.git .

# Or if private repo, use SSH
git clone git@github.com:YOUR_USERNAME/MysteryMixClub.git .
```

## Step 5: Configure Environment

```bash
# Copy production environment template
cp .env.production.example .env.production

# Edit environment file
nano .env.production
```

Update the following values:
```env
# Generate secure passwords
MYSQL_ROOT_PASSWORD=$(openssl rand -base64 32)
MYSQL_PASSWORD=$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -hex 32)

# Set your domain or IP
FRONTEND_URL=https://yourdomain.com
VITE_API_URL=https://yourdomain.com/api/v1
DOMAIN=yourdomain.com
EMAIL=your-email@example.com
```

Save and exit (Ctrl+X, Y, Enter)

## Step 6: Deploy Application

```bash
# Make deploy script executable
chmod +x deploy.sh

# Run deployment
./deploy.sh production
```

The script will:
1. Load environment variables
2. Build Docker images
3. Start containers
4. Run database migrations

## Step 7: Configure Firewall

```bash
# Enable UFW
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# Check status
ufw status
```

## Step 8: Set Up SSL (Let's Encrypt)

### Option A: Using Certbot in Docker

```bash
# Install certbot
apt install certbot python3-certbot-nginx -y

# Get certificate
certbot certonly --standalone \
  --preferred-challenges http \
  -d yourdomain.com \
  -d www.yourdomain.com \
  --email your-email@example.com \
  --agree-tos \
  --non-interactive

# Certificates will be at /etc/letsencrypt/live/yourdomain.com/

# Update nginx config to use SSL (see Step 9)

# Set up auto-renewal
echo "0 0 * * * root certbot renew --quiet" >> /etc/crontab
```

## Step 9: Update Nginx for SSL (if using SSL)

Create `/opt/mysterymixclub/nginx/nginx.conf`:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Proxy to backend API
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Serve frontend
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

Restart: `docker-compose -f docker-compose.prod.yml restart frontend`

## Step 10: Verify Deployment

```bash
# Check container status
docker-compose -f docker-compose.prod.yml ps

# Check logs
docker-compose -f docker-compose.prod.yml logs -f

# Test backend
curl http://localhost:8000/docs

# Test frontend
curl http://localhost
```

Visit your domain or IP address in a browser!

## Maintenance Commands

```bash
# View logs
docker-compose -f docker-compose.prod.yml logs -f [service]

# Restart a service
docker-compose -f docker-compose.prod.yml restart [service]

# Stop all services
docker-compose -f docker-compose.prod.yml down

# Update application (pull latest code and redeploy)
git pull origin main
./deploy.sh production

# Database backup
docker-compose -f docker-compose.prod.yml exec db \
  mysqldump -u root -p$MYSQL_ROOT_PASSWORD mysterymixclub \
  > backup_$(date +%Y%m%d).sql

# Database restore
docker-compose -f docker-compose.prod.yml exec -T db \
  mysql -u root -p$MYSQL_ROOT_PASSWORD mysterymixclub \
  < backup_20240101.sql
```

## Monitoring

```bash
# System resources
htop

# Docker stats
docker stats

# Disk usage
df -h
docker system df
```

## Troubleshooting

### Container won't start
```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs [service]

# Rebuild container
docker-compose -f docker-compose.prod.yml build --no-cache [service]
docker-compose -f docker-compose.prod.yml up -d
```

### Database connection issues
```bash
# Check database is running
docker-compose -f docker-compose.prod.yml ps db

# Check database logs
docker-compose -f docker-compose.prod.yml logs db

# Connect to database
docker-compose -f docker-compose.prod.yml exec db \
  mysql -u root -p$MYSQL_ROOT_PASSWORD mysterymixclub
```

### Out of disk space
```bash
# Clean up Docker
docker system prune -a

# Clean up logs
docker-compose -f docker-compose.prod.yml logs --tail=0 -f > /dev/null &
```

## Security Checklist

- [ ] Firewall configured (UFW)
- [ ] SSL certificate installed
- [ ] Strong database passwords set
- [ ] Strong SECRET_KEY generated
- [ ] Database not exposed publicly
- [ ] Regular backups configured
- [ ] System updates enabled
- [ ] SSH key-only authentication
- [ ] Disable root password login

## Scaling Options

When you need more capacity:

1. **Vertical Scaling**: Resize droplet to larger size
2. **Managed Database**: Migrate to DigitalOcean Managed MySQL
3. **Load Balancer**: Add DigitalOcean Load Balancer
4. **App Platform**: Migrate to managed App Platform
5. **Kubernetes**: Deploy to DigitalOcean Kubernetes (DOKS)

## Alternative: DigitalOcean App Platform

For a fully managed deployment:

1. Create `app.yaml`:
```yaml
name: mysterymixclub
services:
- name: backend
  github:
    repo: YOUR_USERNAME/MysteryMixClub
    branch: main
    deploy_on_push: true
  build_command: cd backend && pip install -r requirements.txt
  run_command: cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
  environment_slug: python
  envs:
  - key: DATABASE_URL
    value: ${db.DATABASE_URL}

- name: frontend
  github:
    repo: YOUR_USERNAME/MysteryMixClub
    branch: main
  build_command: cd frontend && npm install && npm run build
  environment_slug: node-js
  routes:
  - path: /

databases:
- name: db
  engine: MYSQL
  version: "8"
```

2. Deploy: `doctl apps create --spec app.yaml`

Cost: ~$30-40/month but fully managed with auto-scaling.

---

**Need help?** Check the logs, review this guide, or reach out for support!
