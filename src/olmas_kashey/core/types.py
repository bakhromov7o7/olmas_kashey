from enum import Enum
from typing import NewType

class EntityKind(str, Enum):
    USER = "user"
    GROUP = "group"
    CHANNEL = "channel"
    BOT = "bot"
    UNKNOWN = "unknown"

class MembershipState(str, Enum):
    UNKNOWN = "unknown"
    JOINED = "joined"
    LEFT = "left"
    BANNED = "banned"
    PENDING = "pending"
    KICKED = "kicked"
    RESTRICTED = "restricted"

# Value Objects
Username = NewType("Username", str)
InviteLink = NewType("InviteLink", str)
EntityId = NewType("EntityId", int)
