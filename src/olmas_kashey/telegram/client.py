import asyncio
from typing import Any, Callable, TypeVar, Union, List, Optional
from typing_extensions import ParamSpec
from functools import wraps

from telethon import TelegramClient, events, errors
from telethon.tl import functions
from telethon.tl.types import Channel, Chat, TypeInputPeer
from loguru import logger
from olmas_kashey.core.settings import settings

P = ParamSpec("P")
R = TypeVar("R")


def handle_flood_wait(func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        retries = 3
        for attempt in range(retries):
            try:
                return await func(*args, **kwargs)
            except errors.FloodWaitError as e:
                wait_time = e.seconds + 2
                logger.warning(f"FloodWaitError: Sleeping for {wait_time} seconds. Attempt {attempt + 1}/{retries}")
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                raise
        raise errors.FloodWaitError(request=None, capture_message="Max retries reached")

    return wrapper


class OlmasClient:
    def __init__(self) -> None:
        self.client = TelegramClient(
            str(settings.telegram.session_dir / settings.telegram.session_name),
            settings.telegram.api_id, 
            settings.telegram.api_hash,
            proxy=settings.proxy.formatted_proxy()
        )

    async def start(self) -> None:
        await self.client.start(phone=settings.telegram.phone_number)
        logger.info("Telegram Client Started")

    async def stop(self) -> None:
        await self.client.disconnect()
        logger.info("Telegram Client Disconnected")

    @handle_flood_wait
    async def search_public_channels(self, query: str, limit: int = 10) -> List[Union[Channel, Chat]]:
        logger.info(f"Searching for public channels with query: '{query}'")
        result = await self.client(functions.contacts.SearchRequest(
            q=query,
            limit=limit
        ))
        # Filter strictly for Channels/Chats which are essentially groups/channels
        groups = [
            chat for chat in result.chats 
            if isinstance(chat, (Channel, Chat)) and not chat.left
        ]
        logger.info(f"Found {len(groups)} groups for query '{query}'")
        return groups

    @handle_flood_wait
    async def join_channel(self, entity: TypeInputPeer) -> None:
        logger.info(f"Attempting to join entity: {entity}")
        await self.client(functions.channels.JoinChannelRequest(channel=entity))
        logger.info(f"Successfully joined entity: {entity}")

    @handle_flood_wait
    async def get_entity(self, entity: Union[str, int]) -> Any:
        return await self.client.get_entity(entity)

    @handle_flood_wait
    async def check_membership(self, entity: Union[int, str]) -> str:
        """
        Check membership status of the current user in the given channel/group.
        Returns: 'joined', 'left', 'banned', or 'unknown' (strings to map to Enums later).
        """
        try:
            # GetParticipantRequest raises error if not participant
            # We use 'me' as user_id which Telethon resolves
            await self.client(functions.channels.GetParticipantRequest(
                channel=entity,
                participant='me'
            ))
            return "joined"
        except errors.UserNotParticipantError:
            return "left"
        except (errors.ChannelPrivateError, errors.ChannelInvalidError):
            return "banned" # Or removed/inaccessible
        except errors.UserBannedInChannelError:
            return "banned"
        except Exception as e:
            logger.error(f"Error checking membership for {entity}: {e}")
            return "unknown"
