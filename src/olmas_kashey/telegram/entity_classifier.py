from typing import Any, Optional
from telethon.tl.types import User, Chat, Channel

from olmas_kashey.core.types import EntityKind, Username, EntityId
from olmas_kashey.utils.normalize import normalize_username

class ClassifiedEntity:
    def __init__(
        self,
        kind: EntityKind,
        tg_id: int,
        title: Optional[str] = None,
        username: Optional[str] = None
    ):
        self.kind = kind
        self.tg_id = EntityId(tg_id)
        self.title = title
        self.username = Username(normalize_username(username)) if username else None

    def __repr__(self) -> str:
        return f"<ClassifiedEntity(kind={self.kind}, id={self.tg_id}, username={self.username})>"

class EntityClassifier:
    @staticmethod
    def classify(entity: Any) -> ClassifiedEntity:
        # Check for User
        if isinstance(entity, User):
            kind = EntityKind.BOT if entity.bot else EntityKind.USER
            return ClassifiedEntity(
                kind=kind,
                tg_id=entity.id,
                title=f"{entity.first_name or ''} {entity.last_name or ''}".strip() or None,
                username=entity.username
            )

        # Check for Basic Group (Chat)
        if isinstance(entity, Chat):
            # Basic groups are always groups. But often migrated to supergroups.
            return ClassifiedEntity(
                kind=EntityKind.GROUP,
                tg_id=entity.id,
                title=entity.title,
                username=None # Basic groups don't have usernames usually
            )

        # Check for Channel/Supergroup
        if isinstance(entity, Channel):
            if entity.broadcast:
                kind = EntityKind.CHANNEL
            elif entity.megagroup:
                kind = EntityKind.GROUP
            else:
                # Fallback, likely a channel if not explicitly megagroup?
                # Actually broadcast is the main differentiator. 
                # If neither is set?? Should be one.
                # Default to Channel if unsure? Or Group if we want to be safe?
                # Usually: broadcast=True -> Channel. broadcast=False -> Megagroup/Gigagroup.
                kind = EntityKind.GROUP
            
            return ClassifiedEntity(
                kind=kind,
                tg_id=entity.id,
                title=entity.title,
                username=entity.username
            )

        # Unknown
        # Example: InputPeer... we can't classify easily without fetching full entity.
        # Assuming we get full entities from search/get_entity.
        try:
            tg_id = getattr(entity, "id", 0)
            title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
            username = getattr(entity, "username", None)
            return ClassifiedEntity(
                kind=EntityKind.UNKNOWN,
                tg_id=tg_id,
                title=title,
                username=username
            )
        except Exception:
            pass

        # If completely unknown structure
        return ClassifiedEntity(EntityKind.UNKNOWN, 0, title="Unknown")
