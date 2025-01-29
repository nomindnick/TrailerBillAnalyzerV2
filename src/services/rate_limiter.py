import asyncio
import logging
from typing import TypeVar, Callable, Any, Awaitable
from datetime import datetime, timedelta
from collections import deque

T = TypeVar('T')

class RateLimiter:
    """
    Rate limiter for API requests with token bucket algorithm
    """
    def __init__(self, requests_per_minute: int = 50):
        self.logger = logging.getLogger(__name__)
        self.requests_per_minute = requests_per_minute
        self.time_between_requests = 60.0 / requests_per_minute
        self.last_request_time = datetime.now()
        self.request_times = deque(maxlen=requests_per_minute)
        self._lock = asyncio.Lock()

    async def execute(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """
        Execute a function with rate limiting

        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the function execution
        """
        async with self._lock:
            # Calculate time since last request
            now = datetime.now()

            # Clean up old request times
            while self.request_times and (now - self.request_times[0]) > timedelta(minutes=1):
                self.request_times.popleft()

            # If we've made too many requests in the last minute, wait
            if len(self.request_times) >= self.requests_per_minute:
                wait_time = (self.request_times[0] + timedelta(minutes=1) - now).total_seconds()
                if wait_time > 0:
                    self.logger.info(f"Rate limit reached. Waiting {wait_time:.2f} seconds")
                    await asyncio.sleep(wait_time)

            # Add minimum delay between requests
            time_since_last = (now - self.last_request_time).total_seconds()
            if time_since_last < self.time_between_requests:
                delay = self.time_between_requests - time_since_last
                await asyncio.sleep(delay)

            try:
                result = await func(*args, **kwargs)
                self.request_times.append(datetime.now())
                self.last_request_time = datetime.now()
                return result
            except Exception as e:
                self.logger.error(f"Error executing rate-limited function: {str(e)}")
                raise