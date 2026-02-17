from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any
from loguru import logger
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload

from olmas_kashey.db.models import AllowlistItem, Entity, Membership, MembershipState, Event, EntityKind
from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.db.session import get_db

class MembershipService:
    def __init__(self, client: OlmasClient, bot: Optional[Any] = None):
        self.client = client
        self.bot = bot

    async def add_to_allowlist(self, target: str, note: Optional[str] = None) -> bool:
        """Add a target (username/id) to allowlist."""
        normalized = target.strip().lower()
        async for session in get_db():
            stmt = select(AllowlistItem).where(AllowlistItem.target == normalized)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            if existing:
                return False
                
            item = AllowlistItem(target=normalized, note=note)
            session.add(item)
            await session.commit()
            return True
        return False

    async def remove_from_allowlist(self, target: str) -> bool:
        """Remove a target from allowlist."""
        normalized = target.strip().lower()
        async for session in get_db():
            stmt = select(AllowlistItem).where(AllowlistItem.target == normalized)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            if not existing:
                return False
                
            await session.delete(existing)
            await session.commit()
            return True
        return False

    async def list_allowlist(self) -> List[AllowlistItem]:
        async for session in get_db():
            result = await session.execute(select(AllowlistItem))
            return list(result.scalars().all())
        return []

    async def process_joins(self) -> None:
        """
        Check for groups in allowlist that are NOT_JOINED and attempt to join them.
        """
        async for session in get_db():
            now = datetime.now(timezone.utc)

            # Fetch Allowlist
            allowlist_items = (await session.execute(select(AllowlistItem))).scalars().all()
            allowed_targets = {item.target for item in allowlist_items}
            
            if not allowed_targets:
                return

            # Extract allowed_usernames and allowed_ids
            allowed_usernames = {t for t in allowed_targets if not t.isdigit()}
            allowed_ids = {int(t) for t in allowed_targets if t.isdigit()}
            
            stmt = select(Entity).outerjoin(Membership).where(
                (Entity.username.in_(allowed_usernames)) | (Entity.tg_id.in_(allowed_ids)),
                (Membership.state == None) | (Membership.state == MembershipState.NOT_JOINED)
            ).options(selectinload(Entity.memberships))
            
            candidates = (await session.execute(stmt)).scalars().all()
            
            for entity in candidates:
                # Check recent failure event (skip if failed in last 6 hours)
                stmt_event = select(Event).where(
                    Event.entity_id == entity.id,
                    Event.type == "join_failed",
                    Event.created_at >= now - timedelta(hours=6)
                )
                recent_fail = (await session.execute(stmt_event)).scalar_one_or_none()
                if recent_fail:
                    logger.debug(f"Skipping {entity.username or entity.tg_id} due to recent failure.")
                    continue

                logger.info(f"Attempting to join allowed entity: {entity.username or entity.tg_id}")
                
                try:
                    # Join
                    target = entity.username or entity.tg_id
                    await self.client.join_channel(target)
                    
                    # Update Membership
                    if not entity.memberships:
                         mem = Membership(entity_id=entity.id, state=MembershipState.JOINED, joined_at=now)
                         session.add(mem)
                    else:
                         entity.memberships.state = MembershipState.JOINED
                         entity.memberships.joined_at = now
                    
                    # Log Event
                    session.add(Event(entity_id=entity.id, type="join_success"))
                    await session.commit()
                    logger.info(f"Successfully joined {target}")

                    # Notify through bot if available
                    if self.bot:
                        await self.bot.notify_join(entity.title or str(target), entity.username)
                    
                except Exception as e:
                    logger.error(f"Failed to join {entity.username or entity.tg_id}: {e}")
                    session.add(Event(
                        entity_id=entity.id, 
                        type="join_failed", 
                        payload={"error": str(e)}
                    ))
                    await session.commit()
