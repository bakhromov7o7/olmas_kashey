from pathlib import Path
from typing import List, Optional
from pydantic import Field, AnyHttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from enum import Enum

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"

class TelegramSettings(BaseSettings):
    api_id: int = Field(..., description="Telegram API ID")
    api_hash: str = Field(..., description="Telegram API Hash")
    session_dir: Path = Field(default=Path("sessions"), description="Directory to store session files")
    session_name: str = Field(default="olmas_session", description="Session file name")
    phone_number: Optional[str] = Field(default=None, description="Phone number for login")
    
    @field_validator("session_dir")
    @classmethod
    def create_session_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

class DatabaseSettings(BaseSettings):
    url: str = Field(default="sqlite+aiosqlite:///./olmas_kashey.db", description="Database Connection URL")

class DiscoverySettings(BaseSettings):
    rate_limit_per_second: float = Field(default=1.0, description="Rate limit for discovery requests")
    keyword_batch_size: int = Field(default=5, description="Number of keywords to process in a batch")
    batch_interval_seconds: int = Field(default=60, description="Interval between batches")
    
    # Allowlist
    allowed_topics: List[str] = Field(default=["ielts", "uzbekistan", "tashkent"], description="Whitelisted topics/keywords")

class ServiceSettings(BaseSettings):
    scheduler_interval_minutes: int = Field(default=30, ge=1, description="Scheduler interval in minutes")
    enable_auto_join: bool = Field(default=True, description="Whether to auto-join classified groups")

class ProxySettings(BaseSettings):
    url: Optional[AnyHttpUrl] = Field(default=None, description="Proxy URL for Telegram client")
    enabled: bool = Field(default=False, description="Enable proxy")

    def formatted_proxy(self) -> Optional[dict]:
        if not self.enabled or not self.url:
            return None
        
        # Telethon/python-socks expected format
        proxy_type = self.url.scheme
        if "socks5" in proxy_type:
            ptype = "socks5"
        elif "socks4" in proxy_type:
            ptype = "socks4"
        else:
            ptype = "http"
            
        return {
            'proxy_type': ptype,
            'addr': self.url.host,
            'port': self.url.port,
            'username': self.url.username,
            'password': self.url.password,
            'rdns': True
        }

class GroqSettings(BaseSettings):
    api_key: str = Field(..., description="GROQ API Key")
    model: str = Field(default="llama-3.3-70b-versatile", description="GROQ Model")
    max_tokens: int = Field(default=1024, description="Max tokens for response")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )

    env: Environment = Field(default=Environment.LOCAL, alias="APP_ENV")
    log_level: LogLevel = Field(default=LogLevel.INFO)

    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    service: ServiceSettings = Field(default_factory=ServiceSettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    groq: GroqSettings = Field(default_factory=GroqSettings)


settings = Settings()

