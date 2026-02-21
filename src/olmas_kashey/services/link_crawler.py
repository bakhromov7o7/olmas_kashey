import re
from typing import List, Set, Optional, Union, Any
from loguru import logger
from telethon.tl.types import Message, Channel, Chat

from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.telegram.entity_classifier import EntityClassifier
from olmas_kashey.utils.normalize import normalize_link, normalize_username
from olmas_kashey.core.types import EntityKind

class LinkCrawlerService:
    """
    Scans group messages to find and extract Telegram links (t.me/...) and @usernames.
    Used to recursively discover new groups from existing ones.
    """
    def __init__(self, client: OlmasClient):
        self.client = client
        # Regex to find potential telegram links and usernames in text
        self.link_regex = re.compile(r'(?:https?://)?(?:www\.)?t\.me/(?:joinchat/)?([a-zA-Z0-9_+%-/]+)', re.IGNORECASE)
        self.username_regex = re.compile(r'@([a-zA-Z0-9_]{5,32})', re.IGNORECASE)

    async def crawl_group(self, entity_id: Union[int, str], limit: int = 100) -> List[str]:
        """
        Fetch recent messages from a group and extract all unique Telegram links/usernames.
        """
        logger.info(f"Crawling messages for group {entity_id} (limit={limit})")
        found_targets: Set[str] = set()
        
        try:
            messages = await self.client.client.get_messages(entity_id, limit=limit)
            for msg in messages:
                if not msg.text:
                    continue
                
                # Extract links
                links = self.link_regex.findall(msg.text)
                for link in links:
                    normalized = normalize_link(f"t.me/{link}")
                    if normalized:
                        found_targets.add(normalized)
                
                # Extract @usernames
                usernames = self.username_regex.findall(msg.text)
                for uname in usernames:
                    normalized = normalize_username(uname)
                    if normalized:
                        found_targets.add(normalized)
                        
            logger.info(f"Crawler found {len(found_targets)} potential targets in {entity_id}")
            return list(found_targets)
            
        except Exception as e:
            logger.error(f"Failed to crawl group {entity_id}: {e}")
            return []

    async def filter_and_classify(self, targets: List[str]) -> List[Any]:
        """
        Resolves targets and returns only those that are valid Groups/Channels.
        """
        candidates = []
        for target in targets:
            try:
                # Basic rate limiting/jitter could be added here if needed, 
                # but OlmasClient wrapper handled it.
                entity = await self.client.get_entity(target)
                if entity:
                    classified = EntityClassifier.classify(entity)
                    # We only care about groups or maybe channels if allowed
                    if classified.kind in (EntityKind.GROUP, EntityKind.CHANNEL):
                        candidates.append(classified)
            except Exception:
                # Peer not found or private link
                continue
        return candidates
