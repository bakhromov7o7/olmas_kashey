import pytest
from unittest.mock import MagicMock
from telethon.tl.types import User, Chat, Channel

from olmas_kashey.telegram.entity_classifier import EntityClassifier, EntityKind

def test_classify_user():
    # Mock User
    user = User(id=1, first_name="John", last_name="Doe", username="johndoe", bot=False)
    # Telethon objects often need more args but for attribute access this is roughly enough if types match? 
    # Actually Telethon types are strict. Let's use simple mocks or duck typing if possible,
    # OR assume we can instantiate them. Telethon types act like dataclasses mostly.
    
    # Let's try instantiating properly since we import them.
    # User(id, access_hash, first_name, last_name, username, phone, photo, status, bot, ...)
    # Too many args. Let's use MagicMock with spec.
    
    mock_user = MagicMock(spec=User)
    mock_user.id = 123
    mock_user.first_name = "John"
    mock_user.last_name = "Doe"
    mock_user.username = "johndoe"
    mock_user.bot = False
    
    # We must mock isinstance check? 
    # EntityClassifier uses `isinstance(entity, User)`. 
    # MagicMock(spec=User) usually passes isinstance if using standard mock, but sometimes tricky.
    # Let's rely on structural typing or simple class inheritance for test objects if mock fails.
    
    # Better: Create dummy classes inheriting from actual types
    class DummyUser(User):
        def __init__(self, bot=False):
            self.id=1
            self.first_name="A"
            self.last_name=None
            self.username="u"
            self.bot=bot
            
    c = EntityClassifier.classify(DummyUser())
    assert c.kind == EntityKind.USER
    assert c.tg_id == 1
    assert c.username == "u"

    c_bot = EntityClassifier.classify(DummyUser(bot=True))
    assert c_bot.kind == EntityKind.BOT

def test_classify_group():
    class DummyChat(Chat):
        def __init__(self):
            self.id=2
            self.title="G"
            self.username=None # Chat usually none
            
    c = EntityClassifier.classify(DummyChat())
    assert c.kind == EntityKind.GROUP
    assert c.tg_id == 2

def test_classify_channel_supergroup():
    class DummyChannel(Channel):
        def __init__(self, broadcast=False, megagroup=False):
            self.id=3
            self.title="C"
            self.username="ch"
            self.broadcast=broadcast
            self.megagroup=megagroup
            
    # Broadcast -> Channel
    c1 = EntityClassifier.classify(DummyChannel(broadcast=True))
    assert c1.kind == EntityKind.CHANNEL
    
    # Megagroup -> Group
    c2 = EntityClassifier.classify(DummyChannel(megagroup=True))
    assert c2.kind == EntityKind.GROUP
    
    # Neither -> Default to GROUP (safe fallback) or CHANNEL?
    # Logic was GROUP.
    c3 = EntityClassifier.classify(DummyChannel())
    assert c3.kind == EntityKind.GROUP

def test_classify_unknown():
    obj = object()
    c = EntityClassifier.classify(obj)
    assert c.kind == EntityKind.UNKNOWN
    assert c.title == "Unknown"
