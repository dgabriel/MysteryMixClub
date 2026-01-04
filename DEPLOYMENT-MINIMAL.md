# MysteryMixClub - Minimal DigitalOcean Deployment ($6/month)

## Overview

Deploy MysteryMixClub on the smallest DigitalOcean droplet for **$6/month**.

**Droplet Specs:**
- 1GB RAM
- 1 vCPU
- 25GB SSD Storage
- 1TB Transfer

**Memory Allocation:**
- MySQL: 512MB
- Backend: 256MB
- Frontend: 128MB
- System: ~100MB

## Quick Start

### 1. Create Smallest Droplet

**Via DigitalOcean Dashboard:**
```
Region: Choose closest to users
Image: Ubuntu 22.04 LTS
Size: Basic - $6/month (1GB RAM, 1 vCPU, 25GB SSD)
```

**Via CLI:**
```bash
doctl compute droplet create mysterymixclub \
  --region nyc3 \
  --size s-1vcpu-1gb \
  --image ubuntu-22-04-x64 \
  --ssh-keys YOUR_SSH_KEY_ID
```

### 2. Initial Server Setup

```bash
# SSH into droplet
ssh root@YOUR_DROPLET_IP

# Update system
apt update && apt upgrade -y

# Install Docker & Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
apt install docker-compose git -y

# Enable swap (CRITICAL for 1GB RAM)
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Verify swap
free -h
```

### 3. Clone and Configure

```bash
# Create app directory
mkdir -p /opt/mysterymixclub
cd /opt/mysterymixclub

# Clone repository
git clone https://github.com/YOUR_USERNAME/MysteryMixClub.git .

# Create production environment
cp .env.production.example .env.production

# Generate secure credentials
cat > .env.production << EOF
DATABASE_URL=mysql+pymysql://mysterymix:$(openssl rand -base64 24)@db:3306/mysterymixclub
MYSQL_ROOT_PASSWORD=$(openssl rand -base64 24)
MYSQL_DATABASE=mysterymixclub
MYSQL_USER=mysterymix
MYSQL_PASSWORD=$(openssl rand -base64 24)
SECRET_KEY=$(openssl rand -hex 32)
FRONTEND_URL=http://$(curl -s ifconfig.me)
VITE_API_URL=http://$(curl -s ifconfig.me)/api/v1
ENVIRONMENT=production
EOF

# Review and edit if needed
nano .env.production
```

### 4. Deploy

```bash
# Make deploy script executable
chmod +x deploy.sh

# Deploy (first time will take 5-10 minutes due to image builds)
./deploy.sh production
```

### 5. Configure Firewall

```bash
# Set up UFW
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# Verify
ufw status
```

### 6. Access Application

Visit: `http://YOUR_DROPLET_IP`

## Memory Optimization Tips

### Monitor Memory Usage
```bash
# Real-time monitoring
watch -n 2 free -m

# Docker container stats
docker stats

# Check swap usage
swapon --show
```

### If Running Low on Memory

**1. Restart containers to free memory:**
```bash
docker-compose -f docker-compose.prod.yml restart
```

**2. Clear Docker cache:**
```bash
docker system prune -a -f
```

**3. Increase swap:**
```bash
# Increase to 4GB if needed
fallocate -l 4G /swapfile2
chmod 600 /swapfile2
mkswap /swapfile2
swapon /swapfile2
```

**4. Reduce MySQL buffer (if experiencing OOM):**
Edit `mysql-low-memory.cnf`:
```ini
innodb_buffer_pool_size = 64M  # Reduce from 128M
```
Then: `docker-compose -f docker-compose.prod.yml restart db`

## Performance Expectations

### What Works Well:
- ✅ Up to ~100 concurrent users
- ✅ Small to medium leagues (5-20 members)
- ✅ Normal usage patterns
- ✅ Basic load (few requests per second)

### Limitations:
- ⚠️ Slow during builds/deployments
- ⚠️ High load may cause slowdowns
- ⚠️ Database queries may be slower
- ⚠️ Limited concurrent connections

### When to Upgrade:
Upgrade to $12/month (2GB) droplet if:
- Experiencing frequent slowdowns
- Swap usage consistently >50%
- Memory usage consistently >90%
- More than 50 active users
- Multiple large leagues

## Maintenance Commands

```bash
# View memory usage
docker stats --no-stream

# Restart if slow
docker-compose -f docker-compose.prod.yml restart

# Clean up disk space
docker system prune -a
apt autoremove -y
apt clean

# Database backup
docker-compose -f docker-compose.prod.yml exec db \
  mysqldump -u root -p$MYSQL_ROOT_PASSWORD mysterymixclub \
  | gzip > backup_$(date +%Y%m%d).sql.gz
```

## Troubleshooting

### Container keeps restarting (OOM Killed)
```bash
# Check if OOM killed
dmesg | grep -i kill

# Check swap
free -h

# Increase swap or reduce memory limits in docker-compose.prod.yml
```

### Slow performance
```bash
# Check memory
free -m

# Check disk space
df -h

# Check Docker memory
docker stats

# Restart containers
docker-compose -f docker-compose.prod.yml restart
```

### Out of disk space
```bash
# Check usage
df -h
docker system df

# Clean up
docker system prune -a
journalctl --vacuum-time=3d
apt autoremove -y
```

## Upgrade Path

When you need more resources:

**$12/month (2GB RAM):**
```bash
# Via DigitalOcean dashboard: Droplet → Resize → $12 plan
# No data loss, minimal downtime
```

**$18/month (2GB RAM, 2 vCPU):**
- Better for high traffic
- Faster response times

**Managed Database ($15/month):**
- Migrate MySQL to managed service
- Frees up 512MB RAM on droplet
- Better for scaling

## Cost Breakdown

| Item | Cost/Month |
|------|-----------|
| Droplet (1GB) | $6.00 |
| Bandwidth | $0.00 (included) |
| Backups (optional) | $1.20 |
| **Total** | **$6-7/month** |

## Alternative: Use Managed MySQL

To reduce memory usage on the droplet:

**1. Create Managed MySQL Database ($15/month):**
```bash
doctl databases create mysterymix-db \
  --engine mysql \
  --size db-s-1vcpu-1gb
```

**2. Update docker-compose.prod.yml:**
Remove the `db` service and update `DATABASE_URL` to point to managed database.

**3. Benefits:**
- Frees 512MB RAM on droplet
- Automatic backups
- Better reliability
- Total cost: $21/month ($6 droplet + $15 database)

## Checklist

- [ ] Droplet created ($6/month)
- [ ] Swap enabled (2-4GB)
- [ ] Docker installed
- [ ] Repository cloned
- [ ] Environment configured
- [ ] Application deployed
- [ ] Firewall configured
- [ ] Memory monitoring set up
- [ ] Backup strategy planned
- [ ] Monitoring alerts configured (optional)

## Support

If experiencing issues:
1. Check memory: `free -m`
2. Check logs: `docker-compose -f docker-compose.prod.yml logs`
3. Restart: `docker-compose -f docker-compose.prod.yml restart`
4. Review this guide

---

**You're running a full-stack app for $6/month!** 🎉
