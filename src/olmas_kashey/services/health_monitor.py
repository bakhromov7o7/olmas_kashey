from datetime import datetime, timezone
from loguru import logger
from telethon import errors

from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.core.settings import settings

class HealthMonitor:
    def __init__(self, client: OlmasClient):
        self.client = client
        self._is_restricted = False
        self._last_checked = datetime.min.replace(tzinfo=timezone.utc)
        self.check_interval = 3600 # 1 hour
        self.restriction_reason = None

    @property
    def is_restricted(self) -> bool:
        return self._is_restricted

    async def check_health(self) -> bool:
        """
        Check if account is restricted.
        Returns True if HEALTHY (not restricted), False otherwise.
        """
        now = datetime.now(timezone.utc)
        if (now - self._last_checked).total_seconds() < self.check_interval and not self._is_restricted:
             # If healthy, cached result is fine. If restricted, re-check more often? for now simpler logic.
             return True

        logger.info("Performing health check (RESTRICTED MODE detection)...")
        
        try:
            # 1. Check ability to write to Saved Messages (Me)
            # This is a safe "benign action".
            # We send a message to self and delete it? 
            # Or just check if we can resolve "me"?
            # Resolving "me" is read-only. We need a write action to test restriction on writing.
            # But maybe just check @SpamBot first?
            
            # Method 1: @SpamBot
            # If we can't message @SpamBot, that's also an issue.
            # We don't want to spam SpamBot.
            
            # Method 2: Check "me" peer.
            me = await self.client.get_entity("me")
            if not me:
                logger.error("Could not resolve 'me'.")
                return False # Network or auth issue

            # Method 3: Send benign message to self.
            # Only do this if we suspect issues or very infrequently.
            # Let's rely on info from @SpamBot as requested "read status from @SpamBot only as informational"
            
            # Fetch history from SpamBot without sending '/' start
            # This assumes we have a chat history. 
            # If not started, we can't read history.
            # "Do not attempt to circumvent."
            
            # Let's stick to safe "Saved Messages" check for now as primary "can I write" check?
            # User said: "Use a private, user-controlled test chat or saved messages checks that are harmless."
            
            # Send message to self
            msg = await self.client.client.send_message("me", f"Health Check {now.isoformat()}")
            await self.client.client.delete_messages("me", [msg.id])
            
            self._is_restricted = False
            self.restriction_reason = None
            self._last_checked = now
            return True
            
        except errors.PeerFloodError:
            self._set_restricted("PeerFloodError (Spam limitation)")
            return False
        except errors.UserBannedInChannelError:
            self._set_restricted("UserBannedInChannel (Global ban?)")
            return False
        except errors.UserRestrictedError:
             self._set_restricted("UserRestrictedError")
             return False
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            # Don't set restricted on generic error (network), but return False for 'unhealthy'
            return False

    def _set_restricted(self, reason: str):
        if not self._is_restricted:
            logger.critical(f"ACCOUNT RESTRICTED DETECTED: {reason}")
            logger.critical("Entering RESTRICTED MODE. All sensitive operations paused.")
        
        self._is_restricted = True
        self.restriction_reason = reason
        self._last_checked = datetime.now(timezone.utc)
