import asyncio
import random
from datetime import datetime, timezone
from typing import Optional, Any

from loguru import logger
from sqlalchemy import select

from olmas_kashey.core.settings import settings
from olmas_kashey.db.session import get_db
from olmas_kashey.db.models import Membership, MembershipState, Entity
from olmas_kashey.telegram.client import OlmasClient

class BroadcastService:
    def __init__(self, client: OlmasClient, bot: Optional[Any] = None):
        self.client = client
        self.bot = bot
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self.is_running:
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Broadcast Service started.")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Broadcast Service stopped.")

    async def _run_loop(self):
        while self.is_running:
            try:
                if settings.broadcast.enabled and settings.broadcast.message:
                    logger.info(f"Starting broadcast round. Message: '{settings.broadcast.message[:30]}...'")
                    if self.bot and self.bot.bot_client:
                        try:
                            await self.bot.bot_client.send_message(
                                settings.telegram.authorized_user_id,
                                f"📢 **Broadcast boshlandi...**\nMatn: {settings.broadcast.message[:100]}..."
                            )
                        except Exception: pass
                    await self._broadcast_round()
                else:
                    reason = "disabled" if not settings.broadcast.enabled else "empty message"
                    logger.debug(f"Broadcast round skipped: {reason}")
                
                # Wait for the next interval
                interval_seconds = settings.broadcast.interval_minutes * 60
                # Add some jitter to the interval itself
                interval_seconds += random.uniform(-30, 30)
                
                logger.info(f"Broadcast round finished. Waiting {settings.broadcast.interval_minutes}m for next round.")
                if self.bot and self.bot.bot_client:
                    try:
                        await self.bot.bot_client.send_message(
                            settings.telegram.authorized_user_id,
                            f"✅ **Broadcast raundi yakunlandi.**\nNavbatdagisi {settings.broadcast.interval_minutes} minutdan keyin."
                        )
                    except Exception: pass
                
                # Sleep in increments to remain responsive to stop/pause
                end_time = asyncio.get_running_loop().time() + interval_seconds
                while asyncio.get_running_loop().time() < end_time and self.is_running:
                    if self.bot:
                        await self.bot.wait_if_paused()
                    await asyncio.sleep(10)
                    
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
                await asyncio.sleep(60)

    async def _broadcast_round(self):
        """Fetches all joined groups and sends the ad message to each."""
        async for session in get_db():
            # Find all joined groups
            stmt = (
                select(Entity)
                .join(Membership)
                .where(Membership.state == MembershipState.JOINED)
            )
            result = await session.execute(stmt)
            entities = result.scalars().all()
            
            if not entities:
                logger.warning("No joined groups found in database. Did you run './run_discovery sync-groups'?")
                return

            logger.info(f"Broadcasting message to {len(entities)} groups.")
            
            for entity in entities:
                if not self.is_running:
                    break
                
                if self.bot:
                    await self.bot.wait_if_paused()

                try:
                    target = entity.username or entity.tg_id
                    logger.info(f"Sending broadcast to {target}...")
                    
                    await self.client.send_message(target, settings.broadcast.message)
                    logger.info(f"Successfully sent broadcast to {target}")
                    
                    # Optionally notify user for each group (might be too spammy if 100+ groups)
                    # For now, let's only log it or notify if group count is small.
                    
                    # Add a random delay between messages to look human
                    # If Smart Mode is on, OlmasClient._call already adds action delays, 
                    # but we add an extra 'reading/typing' delay here for extra safety.
                    delay = random.uniform(20, 60)
                    if self.bot and getattr(self.bot, 'eco_mode', False):
                        delay *= 2
                    
                    logger.debug(f"Waiting {delay:.1f}s before next broadcast message...")
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    logger.warning(f"Failed to send broadcast to {entity.title} ({entity.tg_id}): {e}")
                    # Continue to next group
                    await asyncio.sleep(5)
