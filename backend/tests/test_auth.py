import pytest
from fastapi import status


class TestSignup:
    """Test suite for signup endpoint"""

    def test_signup_success(self, client):
        """Test successful user signup"""
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "test@example.com",
                "name": "Test User",
                "password": "password123"
            }
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["user"]["email"] == "test@example.com"
        assert data["user"]["name"] == "Test User"
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_signup_duplicate_email(self, client):
        """Test signup with existing email"""
        # Create first user
        client.post(
            "/api/v1/auth/signup",
            json={
                "email": "test@example.com",
                "name": "Test User",
                "password": "password123"
            }
        )
        
        # Try to create duplicate
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "test@example.com",
                "name": "Another User",
                "password": "password456"
            }
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already registered" in response.json()["detail"].lower()

    def test_signup_invalid_email(self, client):
        """Test signup with invalid email format"""
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "invalid-email",
                "name": "Test User",
                "password": "password123"
            }
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestLogin:
    """Test suite for login endpoint"""

    def test_login_success(self, client):
        """Test successful login"""
        # Create user
        client.post(
            "/api/v1/auth/signup",
            json={
                "email": "test@example.com",
                "name": "Test User",
                "password": "password123"
            }
        )
        
        # Login
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "password123"
            }
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user"]["email"] == "test@example.com"
        assert "access_token" in data
        assert "refresh_token" in data

    def test_login_wrong_password(self, client):
        """Test login with incorrect password"""
        # Create user
        client.post(
            "/api/v1/auth/signup",
            json={
                "email": "test@example.com",
                "name": "Test User",
                "password": "password123"
            }
        )
        
        # Login with wrong password
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_nonexistent_user(self, client):
        """Test login with non-existent email"""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "password123"
            }
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetMe:
    """Test suite for /me endpoint"""

    def test_get_me_success(self, client):
        """Test getting current user info"""
        # Create and login user
        signup_response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "test@example.com",
                "name": "Test User",
                "password": "password123"
            }
        )
        token = signup_response.json()["access_token"]
        
        # Get user info
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"

    def test_get_me_no_token(self, client):
        """Test /me without authentication token"""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_me_invalid_token(self, client):
        """Test /me with invalid token"""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid_token_here"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
