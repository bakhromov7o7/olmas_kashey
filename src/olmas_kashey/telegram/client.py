import asyncio
import random
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar, Union

from telethon import TelegramClient, errors
from telethon.tl import functions
from telethon.tl.types import Channel, Chat, TypeInputPeer
from loguru import logger
from olmas_kashey.core.settings import settings
from olmas_kashey.core.cache import TTLCache
from olmas_kashey.utils.normalize import normalize_link, normalize_username

R = TypeVar("R")


class RequestLimiter:
    def __init__(self, concurrency: int, intervals: Dict[str, float]) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._intervals = intervals
        self._next_allowed: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def _throttle(self, method: str) -> None:
        interval = self._intervals.get(method, self._intervals.get("default", 0))
        lock = self._locks.get(method)
        if not lock:
            lock = asyncio.Lock()
            self._locks[method] = lock
        async with lock:
            now = asyncio.get_running_loop().time()
            next_allowed = self._next_allowed.get(method, 0.0)
            wait = next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_allowed[method] = asyncio.get_running_loop().time() + interval

    async def run(self, method: str, fn: Callable[[], Awaitable[R]]) -> R:
        async with self._sem:
            await self._throttle(method)
            return await fn()


class OlmasClient:
    def __init__(self, client: Optional[TelegramClient] = None, bot: Optional[Any] = None) -> None:
        self.bot = bot
        self.client = client or TelegramClient(
            str(settings.telegram.session_dir / settings.telegram.session_name),
            settings.telegram.api_id,
            settings.telegram.api_hash,
            proxy=settings.proxy.formatted_proxy()
        )
        intervals = {
            "default": settings.telegram_limits.default_interval_seconds,
            "search": settings.telegram_limits.search_interval_seconds,
            "resolve": settings.telegram_limits.resolve_interval_seconds,
            "join": settings.telegram_limits.join_interval_seconds,
            "participant": settings.telegram_limits.participant_interval_seconds,
            "message": settings.telegram_limits.message_interval_seconds,
            "dialogs": settings.telegram_limits.dialogs_interval_seconds,
        }
        self._limiter = RequestLimiter(settings.telegram_limits.concurrency, intervals)
        self._flood_backoff_level = 0
        self._search_cache = TTLCache[List[Union[Channel, Chat]]](settings.discovery.query_cache_ttl_seconds)
        self._search_negative_cache = TTLCache[bool](settings.discovery.negative_cache_ttl_seconds)
        self._resolve_cache = TTLCache[Any](settings.discovery.entity_cache_ttl_seconds)
        self.flood_wait_until: Optional[float] = None

    async def start(self) -> None:
        await self.client.start(phone=settings.telegram.phone_number)
        logger.info("Telegram Client Started")

    async def stop(self) -> None:
        await self.client.disconnect()
        logger.info("Telegram Client Disconnected")

    def is_connected(self) -> bool:
        return self.client and self.client.is_connected()

    def _next_backoff(self) -> float:
        base = settings.telegram_limits.backoff_base_seconds
        max_s = settings.telegram_limits.backoff_max_seconds
        # Exponential backoff: base * 2^level
        wait = min(max_s, base * (2 ** self._flood_backoff_level))
        self._flood_backoff_level = min(self._flood_backoff_level + 1, 10)
        # Add jitter 0-25%
        jitter = random.uniform(0, wait * 0.25)
        return wait + jitter

    def _is_flood_like_error(self, err: Exception) -> bool:
        msg = str(err).upper()
        return any(x in msg for x in ["FLOOD", "TOO MANY", "429", "SLOW_DOWN", "LIMIT_REACHED"])

    async def _call(self, method: str, fn: Callable[[], Awaitable[R]], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> R:
        max_attempts = 3
        attempt = 0
        while attempt < max_attempts:
            try:
                result = await self._limiter.run(method, fn)
                self._flood_backoff_level = 0  # Reset on success
                return result
            except errors.FloodWaitError as e:
                wait_time = e.seconds + random.uniform(1, settings.telegram_limits.flood_jitter_seconds + 1)
                logger.warning(f"FloodWaitError: sleeping for {wait_time:.2f}s (Attempt {attempt+1}/{max_attempts})")
                
                if self.bot and hasattr(self.bot, 'notify_flood_wait'):
                    asyncio.create_task(self.bot.notify_flood_wait(wait_time))

                attempt += 1
                if attempt >= max_attempts:
                    raise
                await self._sleep(wait_time)
            except (errors.PeerFloodError, errors.FloodError) as e:
                wait_time = self._next_backoff()
                logger.warning(f"FloodError: backing off for {wait_time:.2f}s (Attempt {attempt+1}/{max_attempts})")
                attempt += 1
                if attempt >= max_attempts:
                    raise
                await self._sleep(wait_time)
            except Exception as e:
                if self._is_flood_like_error(e):
                    wait_time = self._next_backoff()
                    logger.warning(f"Flood-like error ({type(e).__name__}): backing off for {wait_time:.2f}s (Attempt {attempt+1}/{max_attempts})")
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    await self._sleep(wait_time)
                else:
                    raise
        raise errors.FloodWaitError(seconds=60)

    async def _sleep(self, seconds: float):
        """Sleep that respects bot pause and shutdown signals using absolute time."""
        if not self.bot:
            await asyncio.sleep(seconds)
            return

        end_time = asyncio.get_running_loop().time() + seconds
        self.flood_wait_until = end_time
        
        try:
            while True:
                # Check pause/resume
                await self.bot.wait_if_paused()
                
                now = asyncio.get_running_loop().time()
                remaining = end_time - now
                
                if remaining <= 0:
                    break
                
                # Sleep in short bursts to remain responsive to pause/resume
                await asyncio.sleep(min(2.0, remaining))
        finally:
            self.flood_wait_until = None

    async def search_public_channels(self, query: str, limit: int = 10) -> List[Union[Channel, Chat]]:
        key = f"{query.strip().lower()}|{limit}"
        cached = self._search_cache.get(key)
        if cached is not None:
            return cached
        if self._search_negative_cache.has(key):
            return []

        async def _do() -> Any:
            return await self.client(functions.contacts.SearchRequest(
                q=query,
                limit=limit
            ))

        logger.info(f"Searching for public channels with query: '{query}'")
        result = await self._call("search", _do, args=(query,), kwargs={"limit": limit})
        groups = [
            chat for chat in result.chats
            if self._is_search_candidate(chat)
        ]
        if groups:
            self._search_cache.set(key, groups)
        else:
            self._search_negative_cache.set(key, True, ttl_seconds=settings.discovery.negative_cache_ttl_seconds)
        logger.info(f"Found {len(groups)} groups for query '{query}'")
        return groups

    async def join_channel(self, entity: TypeInputPeer) -> None:
        logger.info(f"Attempting to join entity: {entity}")

        async def _do() -> Any:
            return await self.client(functions.channels.JoinChannelRequest(channel=entity))

        await self._call("join", _do, args=(entity,), kwargs={})
        logger.info(f"Successfully joined entity: {entity}")

    async def get_entity(self, entity: Union[str, int]) -> Any:
        key = self._normalize_entity_key(entity)
        cached = self._resolve_cache.get(key)
        if cached is not None:
            return cached

        async def _do() -> Any:
            return await self.client.get_entity(entity)

        result = await self._call("resolve", _do, args=(entity,), kwargs={})
        self._resolve_cache.set(key, result)
        return result

    async def send_message(self, entity: Union[str, int, TypeInputPeer], message: str) -> None:
        logger.info(f"Sending message to {entity}")

        async def _do() -> Any:
            return await self.client.send_message(entity, message)

        await self._call("message", _do, args=(entity, message), kwargs={})
        logger.info(f"Message sent to {entity}")

    async def check_membership(self, entity: Union[int, str]) -> str:
        """
        Check membership status of the current user in the given channel/group.
        Returns: 'joined', 'left', 'banned', or 'unknown' (strings to map to Enums later).
        """
        try:
            async def _do() -> Any:
                return await self.client(functions.channels.GetParticipantRequest(
                    channel=entity,
                    participant='me'
                ))

            await self._call("participant", _do, args=(entity,), kwargs={})
            return "joined"
        except errors.UserNotParticipantError:
            return "left"
        except (errors.ChannelPrivateError, errors.ChannelInvalidError):
            return "banned"
        except errors.UserBannedInChannelError:
            return "banned"
        except Exception as e:
            logger.error(f"Error checking membership for {entity}: {e}")
            return "unknown"

    async def get_joined_groups(self) -> List[Union[Channel, Chat]]:
        """
        Fetch all dialogs and filter for joined groups/channels.
        """
        logger.info("Fetching all joined groups from Telegram...")

        async def _do() -> Any:
            return await self.client.get_dialogs()

        dialogs = await self._call("dialogs", _do, args=(), kwargs={})
        groups = [
            d.entity for d in dialogs
            if isinstance(d.entity, (Channel, Chat))
        ]
        logger.info(f"Found {len(groups)} joined groups on Telegram.")
        return groups

    def _normalize_entity_key(self, entity: Union[str, int]) -> str:
        if isinstance(entity, str):
            raw = entity.strip()
            if "t.me/" in raw or "telegram.me/" in raw:
                normalized = normalize_link(raw)
                if normalized:
                    return normalized
            if raw.startswith("@") or re.fullmatch(r"[A-Za-z0-9_]{5,32}", raw):
                normalized = normalize_username(raw)
                if normalized:
                    return normalized
            return raw.lower()
        return str(entity)

    def _is_search_candidate(self, chat: Any) -> bool:
        chat_class = getattr(chat, "__class__", None)
        if isinstance(chat, Chat) or chat_class is Chat:
            return True
        if isinstance(chat, Channel) or chat_class is Channel:
            if getattr(chat, "megagroup", False):
                return True
            return settings.discovery.allow_channels
        return False
