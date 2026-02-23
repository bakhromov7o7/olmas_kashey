from pathlib import Path
from typing import List, Optional
from pydantic import Field, AnyUrl, PostgresDsn, field_validator
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
    bot_token: Optional[str] = Field(default=None, description="Telegram Bot Token")
    authorized_user_id: Optional[int] = Field(default=None, description="Telegram ID of the authorized admin")
    
    @field_validator("session_dir")
    @classmethod
    def create_session_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

class TelegramRateLimitSettings(BaseSettings):
    concurrency: int = Field(default=3, ge=1, description="Max concurrent Telegram requests")
    default_interval_seconds: float = Field(default=2.0, ge=0, description="Default minimum interval between requests")
    search_interval_seconds: float = Field(default=8.0, ge=0, description="Min interval for search requests")
    resolve_interval_seconds: float = Field(default=3.0, ge=0, description="Min interval for resolve requests")
    join_interval_seconds: float = Field(default=15.0, ge=0, description="Min interval for join requests")
    participant_interval_seconds: float = Field(default=5.0, ge=0, description="Min interval for participant requests")
    message_interval_seconds: float = Field(default=5.0, ge=0, description="Min interval for message requests")
    dialogs_interval_seconds: float = Field(default=5.0, ge=0, description="Min interval for dialogs requests")
    flood_jitter_seconds: float = Field(default=3.0, ge=0, description="Jitter added to FloodWait sleeps")
    backoff_base_seconds: float = Field(default=3.0, ge=0, description="Base seconds for exponential backoff")
    backoff_max_seconds: float = Field(default=120.0, ge=0, description="Max seconds for exponential backoff")

class DatabaseSettings(BaseSettings):
    url: str = Field(default="sqlite+aiosqlite:///./olmas_kashey.db", description="Database Connection URL")

class DiscoverySettings(BaseSettings):
    rate_limit_per_second: float = Field(default=0.3, description="Rate limit for discovery requests")
    keyword_batch_size: int = Field(default=5, description="Number of keywords to process in a batch")
    batch_interval_seconds: int = Field(default=30, description="Interval between batches")
    max_query_variants: int = Field(default=25, description="Max expanded search queries per discovery")
    max_results_per_query: int = Field(default=15, description="Max results per search query")
    max_ranked_candidates: int = Field(default=20, description="Max ranked candidates to return")
    min_confidence: float = Field(default=0.45, ge=0, le=1, description="Minimum confidence to return a candidate")
    high_confidence: float = Field(default=0.75, ge=0, le=1, description="High confidence threshold to accept best match")
    allow_channels: bool = Field(default=False, description="Whether to include channels in discovery results")
    query_cache_ttl_seconds: int = Field(default=21600, ge=0, description="TTL for query cache in seconds")
    negative_cache_ttl_seconds: int = Field(default=900, ge=0, description="TTL for negative query cache in seconds")
    entity_cache_ttl_seconds: int = Field(default=86400, ge=0, description="TTL for entity cache in seconds")
    
    # Evolution & Adaptive Planning
    evolution_threshold: int = Field(default=3, description="New groups found before triggering evolution")
    max_keyword_age_days: int = Field(default=7, description="Max days a keyword stays fresh")
    backoff_factor: float = Field(default=2.0, description="Delay multiplier for failed keywords")
    
    # Safety & Human-like behavior
    join_delay_min: int = Field(default=30, description="Min seconds to wait before joining")
    join_delay_max: int = Field(default=30, description="Max seconds to wait before joining")
    message_delay_min: int = Field(default=20, description="Min seconds to wait between messages")
    message_delay_max: int = Field(default=60, description="Max seconds to wait between messages")
    
    # Allowlist
    allowed_topics: List[str] = Field(default=["ielts", "uzbekistan", "tashkent"], description="Whitelisted topics/keywords")

class ServiceSettings(BaseSettings):
    scheduler_interval_seconds: int = Field(default=1800, ge=10, description="Scheduler interval in seconds")
    enable_auto_join: bool = Field(default=True, description="Whether to auto-join classified groups")
    smart_mode: bool = Field(default=True, description="Whether Smart Mode AI is active")

class ProxySettings(BaseSettings):
    url: Optional[AnyUrl] = Field(default=None, description="Proxy URL for Telegram client")
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
    telegram_limits: TelegramRateLimitSettings = Field(default_factory=TelegramRateLimitSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    service: ServiceSettings = Field(default_factory=ServiceSettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    groq: GroqSettings = Field(default_factory=GroqSettings)


settings = Settings()
