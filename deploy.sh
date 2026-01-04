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
docker compose -f docker-compose.prod.yml down

# Build and start containers
echo "🔨 Building containers..."
docker compose -f docker-compose.prod.yml build --no-cache

echo "🚀 Starting containers..."
docker compose -f docker-compose.prod.yml up -d

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
sleep 10

# Run database migrations
echo "📊 Running database migrations..."
docker compose -f docker-compose.prod.yml exec -T backend alembic upgrade head

echo "✅ Deployment complete!"
echo ""
echo "📋 Container status:"
docker compose -f docker-compose.prod.yml ps

echo ""
echo "🌐 Application should be available at: $FRONTEND_URL"
echo ""
echo "📝 Useful commands:"
echo "  View logs:    docker compose -f docker-compose.prod.yml logs -f"
echo "  Stop:         docker compose -f docker-compose.prod.yml down"
echo "  Restart:      docker compose -f docker-compose.prod.yml restart"
