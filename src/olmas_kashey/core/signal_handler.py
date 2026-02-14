import signal
import asyncio
from loguru import logger
from typing import List, Callable, Awaitable

class SignalHandler:
    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._handlers: List[Callable[[], Awaitable[None]]] = []
        self._signals = [signal.SIGINT, signal.SIGTERM]
    
    def install(self):
        loop = asyncio.get_running_loop()
        for sig in self._signals:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._handle(s)))
            
    async def _handle(self, sig):
        logger.warning(f"Received signal {sig.name}...")
        self._shutdown_event.set()
        
        logger.info("Executing shutdown handlers...")
        for handler in self._handlers:
            try:
                await handler()
            except Exception as e:
                logger.error(f"Error in shutdown handler: {e}")
                
        logger.info("Shutdown complete.")
        # We don't force exit here, we let the main loop break on shutdown_event
        
    def add_handler(self, handler: Callable[[], Awaitable[None]]):
        self._handlers.append(handler)
        
    async def wait(self):
        """Wait until the shutdown signal is received."""
        await self._shutdown_event.wait()

    async def sleep(self, seconds: float) -> bool:
        """
        Wait for 'seconds' or until shutdown is requested.
        Returns True if shutdown was requested, False if timeout reached.
        """
        if self.check_shutdown:
            return True
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def check_shutdown(self) -> bool:
        return self._shutdown_event.is_set()
