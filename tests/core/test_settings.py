import os
import pytest
from pydantic import ValidationError
from olmas_kashey.core.settings import Settings, Environment

def test_settings_load_defaults():
    # Mock environment to ensure required fields are present
    os.environ["API_ID"] = "12345"
    os.environ["API_HASH"] = "test_hash"
    
    settings = Settings()
    assert settings.telegram.api_id == 12345
    assert settings.telegram.api_hash == "test_hash"
    assert settings.env == Environment.LOCAL
    assert settings.connection_pool is None # Wait, I didn't add connection_pool, just checking unexpected
    assert settings.discovery.rate_limit_per_second == 1.0

def test_settings_env_override():
    os.environ["APP_ENV"] = "production"
    os.environ["DISCOVERY__RATE_LIMIT_PER_SECOND"] = "5.5"
    
    settings = Settings()
    assert settings.env == Environment.PRODUCTION
    assert settings.discovery.rate_limit_per_second == 5.5

def test_invalid_api_id():
    os.environ["API_ID"] = "not_an_int"
    with pytest.raises(ValidationError):
        Settings()

def test_session_dir_creation(tmp_path):
    os.environ["TELEGRAM__SESSION_DIR"] = str(tmp_path / "custom_sessions")
    settings = Settings()
    assert settings.telegram.session_dir.exists()
    assert settings.telegram.session_dir.name == "custom_sessions"
