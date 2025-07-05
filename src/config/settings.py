"""
Application settings and configuration management.

Uses pydantic-settings for environment variable management with validation.
"""

from typing import List, Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings
from enum import Enum
import os


class LogLevel(str, Enum):
    """Supported logging levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # MCP Server Configuration
    crawl4ai_mcp_url: str = Field(
        default="http://localhost:8051/sse",
        description="Crawl4AI RAG MCP server URL"
    )
    supabase_project_ref: str = Field(
        ...,
        description="Supabase project reference ID"
    )
    supabase_access_token: str = Field(
        ...,
        description="Supabase access token"
    )
    github_personal_access_token: Optional[str] = Field(
        default=None,
        description="GitHub personal access token for Actions and repository access"
    )
    digitalocean_api_token: Optional[str] = Field(
        default=None,
        description="DigitalOcean API token for deployment"
    )
    
    # Application Configuration
    notification_email: str = Field(
        ...,
        description="Email address for receiving notifications"
    )
    scrape_interval_minutes: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Interval between scraping runs in minutes"
    )
    alert_cooldown_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Hours to wait before re-alerting for same availability"
    )
    
    # Email Configuration
    smtp_server: str = Field(
        default="smtp.gmail.com",
        description="SMTP server for sending notifications"
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port"
    )
    smtp_username: str = Field(
        ...,
        description="SMTP username for authentication"
    )
    smtp_password: str = Field(
        ...,
        description="SMTP password or app password"
    )
    
    # Development Settings
    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging level"
    )
    
    # Rate Limiting
    max_requests_per_minute: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum requests per minute to avoid rate limiting"
    )
    backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=5.0,
        description="Exponential backoff multiplier for retries"
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of retry attempts"
    )
    
    # Database Settings
    db_pool_size: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Database connection pool size"
    )
    db_max_overflow: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum database connection overflow"
    )
    
    # Security
    secret_key: str = Field(
        ...,
        min_length=32,
        description="Secret key for session management"
    )
    
    @validator('notification_email', 'smtp_username')
    def validate_email(cls, v: str) -> str:
        """Validate email format."""
        if '@' not in v or '.' not in v.split('@')[1]:
            raise ValueError('Invalid email format')
        return v.lower()
    
    @validator('crawl4ai_mcp_url', 'supabase_project_ref')
    def validate_urls(cls, v: str) -> str:
        """Validate URL format."""
        if not v or len(v.strip()) == 0:
            raise ValueError('URL cannot be empty')
        return v.strip()
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


def get_settings() -> Settings:
    """
    Get application settings instance.
    
    Returns:
        Settings: Configured settings instance
    """
    return Settings()


# Global settings instance
settings = get_settings()