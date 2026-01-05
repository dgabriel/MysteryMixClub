#!/bin/bash

# MysteryMixClub Deployment Script
# Usage: ./deploy.sh [environment]
# Example: ./deploy.sh production

set -e

ENVIRONMENT=${1:-production}

echo "🚀 Deploying MysteryMixClub to $ENVIRONMENT..."

# Check if .env file exists
if [ ! -f ".env.$ENVIRONMENT" ]; then
    echo "❌ Error: .env.$ENVIRONMENT file not found!"
    echo "Please create .env.$ENVIRONMENT from .env.production.example"
    exit 1
fi

# Load environment variables
export $(cat .env.$ENVIRONMENT | grep -v '^#' | xargs)

echo "✓ Environment variables loaded"

# Pull latest code (if deploying from git)
if [ -d ".git" ]; then
    echo "📥 Pulling latest code..."
    git pull origin main
    echo "✓ Code updated"
fi

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml down

# Build and start containers
echo "🔨 Building containers..."
docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml build --no-cache

echo "🚀 Starting containers..."
docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml up -d

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
echo "This may take 30-60 seconds on first startup..."

# Wait for MySQL to be ready (up to 2 minutes)
RETRY_COUNT=0
MAX_RETRIES=24  # 24 * 5 seconds = 2 minutes

until docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml exec -T db mysql -u root -p"$MYSQL_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo "❌ Database failed to start after 2 minutes"
    echo "Check logs with: docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml logs db"
    exit 1
  fi
  echo "Waiting for database... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 5
done

echo "✓ Database is ready!"

# Run database migrations
echo "📊 Running database migrations..."
docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml exec -T backend alembic upgrade head

echo "✅ Deployment complete!"
echo ""
echo "📋 Container status:"
docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml ps

echo ""
echo "🌐 Application should be available at: $FRONTEND_URL"
echo ""
echo "📝 Useful commands:"
echo "  View logs:    docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml logs -f"
echo "  Stop:         docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml down"
echo "  Restart:      docker compose --env-file .env.$ENVIRONMENT -f docker-compose.prod.yml restart"
