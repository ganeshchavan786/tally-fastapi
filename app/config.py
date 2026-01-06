"""
Configuration Management Module
Loads and manages application configuration from config.yaml
"""

import os
from pathlib import Path
from typing import List, Optional
import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class TallyConfig(BaseModel):
    """Tally connection configuration"""
    server: str = "localhost"
    port: int = 9000
    company: str = ""
    from_date: str = "2025-04-01"
    to_date: str = "2026-03-31"


class DatabaseConfig(BaseModel):
    """Database configuration"""
    path: str = "./tally.db"


class SyncConfig(BaseModel):
    """Sync configuration"""
    mode: str = "full"
    batch_size: int = 1000


class ApiConfig(BaseModel):
    """API configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = ["http://localhost:3000"]


class DebugConfig(BaseModel):
    """Debug mode configuration"""
    enabled: bool = False
    verbose_logging: bool = False
    log_sql_queries: bool = False
    log_timing: bool = False
    log_memory: bool = False
    log_http_details: bool = False


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = "INFO"
    file: str = "./logs/app.log"
    max_size: int = 10
    backup_count: int = 5
    console: bool = True
    colorize: bool = True


class RetryConfig(BaseModel):
    """Retry configuration"""
    enabled: bool = True
    max_attempts: int = 3
    initial_delay: int = 5
    strategy: str = "exponential"
    backoff_multiplier: int = 2
    max_delay: int = 60


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration"""
    enabled: bool = True
    failure_threshold: int = 5
    recovery_timeout: int = 60


class HealthConfig(BaseModel):
    """Health check configuration"""
    check_interval: int = 30
    tally_timeout: int = 5
    database_timeout: int = 2


class AppConfig(BaseModel):
    """Main application configuration"""
    tally: TallyConfig = TallyConfig()
    database: DatabaseConfig = DatabaseConfig()
    sync: SyncConfig = SyncConfig()
    api: ApiConfig = ApiConfig()
    debug: DebugConfig = DebugConfig()
    logging: LoggingConfig = LoggingConfig()
    retry: RetryConfig = RetryConfig()
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    health: HealthConfig = HealthConfig()


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file"""
    config_file = Path(config_path)
    
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
            return AppConfig(**config_data)
    
    return AppConfig()


def save_config(config: AppConfig, config_path: str = "config.yaml") -> None:
    """Save configuration to YAML file"""
    config_file = Path(config_path)
    
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, allow_unicode=True)


# Global configuration instance
config = load_config()
