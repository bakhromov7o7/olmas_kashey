import pytest
from olmas_kashey.utils.normalize import normalize_username, normalize_link

def test_normalize_username():
    assert normalize_username("@UserName") == "username"
    assert normalize_username("  foo_BAR  ") == "foo_bar"
    assert normalize_username(None) is None
    assert normalize_username("") is None

def test_normalize_link():
    assert normalize_link("https://t.me/username") == "username"
    assert normalize_link("http://telegram.me/Username_Bot") == "username_bot"
    assert normalize_link("t.me/somechannel/123") == "somechannel"
    assert normalize_link("https://t.me/joinchat/AxByCz") == "axbycz" # Assuming basic strip
    assert normalize_link("just_a_username") == "just_a_username"
    assert normalize_link(None) is None
