"""Application configuration using Pydantic Settings."""

import os
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Core settings
    SECRET_KEY: str = Field(..., min_length=32)
    ADMIN_SECRET_KEY: str = Field(..., min_length=32)
    ENVIRONMENT: str = Field(default="development")
    DEBUG: bool = Field(default=False)

    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    DATABASE_URL_ASYNC: str = Field(..., env="DATABASE_URL_ASYNC")

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Security
    SESSION_COOKIE_NAME: str = Field(default="identityforge_session")
    SESSION_COOKIE_SECURE: bool = Field(default=False)
    SESSION_COOKIE_SAMESITE: str = Field(default="lax")
    SESSION_LIFETIME_HOURS: int = Field(default=8)

    # Rate limiting
    MAX_LOGIN_ATTEMPTS: int = Field(default=5)
    LOGIN_LOCKOUT_MINUTES: int = Field(default=15)

    # Admin
    ADMIN_EMAIL: str = Field(default="admin@identityforge.local")
    ADMIN_FIRST_NAME: str = Field(default="System")
    ADMIN_LAST_NAME: str = Field(default="Administrator")

    # API
    API_V1_PREFIX: str = Field(default="/api/v1")
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()