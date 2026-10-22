from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from src import config


class AuthRepository:
    def list(self, limit, cursor=None, owner_id=None, kind=None):
        return [], None

    def ensure_schema(self):
        return None


class AuthJobManager:
    def submit(self, brief, params, owner_id=None, corpus=None):
        return None

    def get(self, job_id, owner_id=None):
        return None

    def shutdown(self):
        return None


def test_protected_routes_require_supabase_bearer_token(monkeypatch):
    monkeypatch.setattr(config, "AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "test-secret-that-is-at-least-32-bytes")
    monkeypatch.setattr(config, "SUPABASE_JWKS_URL", None)
    monkeypatch.setattr(config, "SUPABASE_ISSUER", None)
    app = create_app(
        repository=AuthRepository(),
        job_manager=AuthJobManager(),
        initialize_database=False,
        indexed_count=10,
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/runs").status_code == 401
        token = jwt.encode(
            {
                "sub": str(uuid4()),
                "aud": "authenticated",
                "role": "authenticated",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            "test-secret-that-is-at-least-32-bytes",
            algorithm="HS256",
        )
        response = client.get("/api/v1/runs", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


def test_invalid_auth_token_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "test-secret-that-is-at-least-32-bytes")
    monkeypatch.setattr(config, "SUPABASE_JWKS_URL", None)
    monkeypatch.setattr(config, "SUPABASE_ISSUER", None)
    app = create_app(
        repository=AuthRepository(),
        job_manager=AuthJobManager(),
        initialize_database=False,
        indexed_count=10,
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/runs", headers={"Authorization": "Bearer invalid"})
        assert response.status_code == 401


def test_production_requires_security_configuration(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "AUTH_REQUIRED", False)
    monkeypatch.setattr(config, "DATABASE_URL", None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "SUPABASE_URL", None)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", None)
    monkeypatch.setattr(config, "SUPABASE_JWKS_URL", None)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    app = create_app(
        repository=AuthRepository(),
        job_manager=AuthJobManager(),
        initialize_database=False,
        indexed_count=10,
    )
    with pytest.raises(RuntimeError, match="AUTH_REQUIRED"):
        with TestClient(app):
            pass


def test_demo_configuration_allows_memory_jobs(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "demo")
    monkeypatch.setattr(config, "AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://demo")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "demo-key")
    monkeypatch.setattr(config, "SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "test-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://demo.vercel.app")
    app = create_app(
        repository=AuthRepository(),
        job_manager=AuthJobManager(),
        initialize_database=False,
        indexed_count=10,
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.post(
            "/api/v1/match-jobs",
            json={
                "brief": {"goal": "at-home strength training for Gen Z", "platform": "Any", "audience": "", "vibe": "warm"},
                "params": {"top_k": 3, "top_n": 1},
            },
        )
        assert response.status_code == 401
