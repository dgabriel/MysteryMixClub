# MysteryMixClub

A music discovery league platform where users can join leagues, submit songs based on themes, vote on submissions, and compete on leaderboards.

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + MySQL
- **Frontend**: React + TypeScript + Vite (coming soon)
- **Infrastructure**: Docker + Docker Compose
- **Auth**: JWT tokens with email/password
- **Music API**: Songlink/Odesli
- **Email**: SendGrid

## Project Structure

```
MysteryMixClub/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/v1/      # API routes
│   │   ├── core/        # Core functionality (security, database)
│   │   ├── models/      # SQLAlchemy models
│   │   ├── schemas/     # Pydantic schemas
│   │   ├── services/    # Business logic
│   │   ├── utils/       # Utilities
│   │   └── main.py      # FastAPI app entry
│   ├── alembic/         # Database migrations
│   ├── tests/           # Tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/            # React frontend (coming soon)
├── terraform/           # Infrastructure as Code (coming soon)
├── docker-compose.yml   # Local development
└── Makefile            # Common commands
```

## Quick Start

### First Time Setup

1. **Initialize the project**:
   ```bash
   make init
   ```

   This will:
   - Create `.env` file from `.env.example`
   - Build Docker containers
   - Start services (backend + MySQL)
   - Run database migrations

2. **Access the API**:
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - Health Check: http://localhost:8000/health

### Common Commands

```bash
# Start services
make up

# Stop services
make down

# View logs
make logs

# Run database migrations
make migrate

# Create a new migration
make migrate-create

# Access backend shell
make shell-backend

# Access MySQL shell
make shell-db

# Run tests
make test-backend

# Clean everything (including volumes)
make clean

# See all available commands
make help
```

## API Endpoints

### Authentication

- `POST /api/v1/auth/signup` - Create new user account
- `POST /api/v1/auth/login` - Login and get JWT tokens
- `GET /api/v1/auth/me` - Get current user info (requires authentication)

### Example: Signup

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "name": "John Doe",
    "password": "securepassword123"
  }'
```

### Example: Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "securepassword123"
  }'
```

### Example: Get Current User

```bash
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Development

### Environment Variables

Copy `backend/.env.example` to `backend/.env` and update:

- `SECRET_KEY`: Use a secure random key (generate with `openssl rand -hex 32`)
- `DATABASE_URL`: MySQL connection string
- `SENDGRID_API_KEY`: Your SendGrid API key (optional for development)

### Database Migrations

**Create a new migration** after modifying models:
```bash
make migrate-create
# Enter migration name when prompted
```

**Run migrations**:
```bash
make migrate
```

**Rollback last migration**:
```bash
make migrate-downgrade
```

### Running Tests

```bash
make test-backend
```

With coverage report:
```bash
make test-backend-cov
```

## Current Status

### ✅ Phase 1 Completed
- [x] Project structure
- [x] Docker Compose setup
- [x] FastAPI backend with authentication
- [x] JWT token system
- [x] User model and database migrations
- [x] Auth API endpoints (signup, login, me)
- [x] Makefile for common commands

### 🚧 In Progress
- [ ] React frontend with TypeScript
- [ ] Frontend authentication flow
- [ ] End-to-end testing

### 📋 Upcoming Phases
- **Phase 2**: League Management
- **Phase 3**: Rounds & Submissions
- **Phase 4**: Voting System
- **Phase 5**: Results & Leaderboard
- **Phase 6**: Playlist Features
- **Phase 7**: Email Notifications & Production Deployment

## Next Steps

1. **Test the backend**:
   ```bash
   # Start services
   make up

   # Check if backend is running
   curl http://localhost:8000/health

   # Try creating a user
   curl -X POST http://localhost:8000/api/v1/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email":"test@test.com","name":"Test User","password":"password123"}'
   ```

2. **Proceed to React frontend setup** (Phase 1 continuation)

3. **Move to Phase 2** (League Management)

## Troubleshooting

### Database connection errors
- Ensure MySQL container is healthy: `docker-compose ps`
- Check logs: `make logs`
- Wait a few seconds after starting for MySQL to initialize

### Permission errors
- Try running migrations manually: `make migrate`
- Check if `.env` file exists in `backend/` directory

### Port already in use
- Stop conflicting services on ports 8000 (backend) or 3306 (MySQL)
- Or modify ports in `docker-compose.yml`

## Contributing

This is a personal project. Refer to the implementation plan in `.claude/plans/` for detailed roadmap.

## License

Private project - All rights reserved
