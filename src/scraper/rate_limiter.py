"""
Rate limiting utilities for respectful web scraping.

Implements rate limiting to avoid overwhelming target websites and respect terms of service.
"""

import asyncio
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Async rate limiter for controlling request frequency.
    
    Implements token bucket algorithm with exponential backoff for errors.
    """
    
    def __init__(
        self,
        requests_per_minute: int = 2,
        burst_size: Optional[int] = None,
        backoff_multiplier: float = 2.0,
        max_backoff_seconds: float = 300.0
    ):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum requests per minute
            burst_size: Maximum burst requests (defaults to requests_per_minute)
            backoff_multiplier: Exponential backoff multiplier
            max_backoff_seconds: Maximum backoff time in seconds
        """
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size or requests_per_minute
        self.backoff_multiplier = backoff_multiplier
        self.max_backoff_seconds = max_backoff_seconds
        
        # Token bucket parameters
        self.tokens = float(self.burst_size)
        self.last_update = time.time()
        self.token_rate = requests_per_minute / 60.0  # tokens per second
        
        # Backoff tracking
        self.consecutive_errors = 0
        self.last_error_time: Optional[datetime] = None
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> None:
        """
        Acquire tokens for making requests.
        
        Args:
            tokens: Number of tokens to acquire
            
        Raises:
            ValueError: If tokens requested exceeds burst size
        """
        if tokens > self.burst_size:
            raise ValueError(f"Requested {tokens} tokens exceeds burst size {self.burst_size}")
        
        async with self._lock:
            await self._wait_for_tokens(tokens)
            self.tokens -= tokens
            
            logger.debug(f"Acquired {tokens} tokens, {self.tokens:.2f} remaining")
    
    async def _wait_for_tokens(self, tokens: int) -> None:
        """Wait until sufficient tokens are available."""
        while True:
            self._update_tokens()
            
            if self.tokens >= tokens:
                break
            
            # Calculate wait time for next token
            time_for_next_token = (tokens - self.tokens) / self.token_rate
            wait_time = min(time_for_next_token, 1.0)  # Wait at most 1 second at a time
            
            logger.debug(f"Rate limited: waiting {wait_time:.2f}s for {tokens} tokens")
            await asyncio.sleep(wait_time)
    
    def _update_tokens(self) -> None:
        """Update token count based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        
        # Add tokens based on elapsed time
        new_tokens = elapsed * self.token_rate
        self.tokens = min(self.burst_size, self.tokens + new_tokens)
        self.last_update = now
    
    async def handle_error(self, error: Exception) -> None:
        """
        Handle errors with exponential backoff.
        
        Args:
            error: The exception that occurred
        """
        self.consecutive_errors += 1
        self.last_error_time = datetime.utcnow()
        
        # Calculate backoff time
        backoff_time = min(
            self.backoff_multiplier ** (self.consecutive_errors - 1),
            self.max_backoff_seconds
        )
        
        logger.warning(
            f"Error occurred (attempt {self.consecutive_errors}): {error}. "
            f"Backing off for {backoff_time:.2f} seconds"
        )
        
        await asyncio.sleep(backoff_time)
    
    def handle_success(self) -> None:
        """Reset error tracking after successful request."""
        if self.consecutive_errors > 0:
            logger.info(f"Successful request after {self.consecutive_errors} errors")
            self.consecutive_errors = 0
            self.last_error_time = None
    
    @property
    def is_backing_off(self) -> bool:
        """Check if currently in backoff period."""
        if not self.last_error_time:
            return False
        
        backoff_time = min(
            self.backoff_multiplier ** (self.consecutive_errors - 1),
            self.max_backoff_seconds
        )
        
        return (datetime.utcnow() - self.last_error_time).total_seconds() < backoff_time
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current rate limiter status.
        
        Returns:
            Dict with current status information
        """
        self._update_tokens()
        
        return {
            "tokens_available": self.tokens,
            "tokens_per_minute": self.requests_per_minute,
            "consecutive_errors": self.consecutive_errors,
            "is_backing_off": self.is_backing_off,
            "last_error_time": self.last_error_time.isoformat() if self.last_error_time else None
        }


class HostRateLimiter:
    """
    Rate limiter that manages limits per host.
    
    Useful for scraping multiple domains with different rate limits.
    """
    
    def __init__(self, default_requests_per_minute: int = 2):
        """
        Initialize host-based rate limiter.
        
        Args:
            default_requests_per_minute: Default rate limit for unknown hosts
        """
        self.default_requests_per_minute = default_requests_per_minute
        self.limiters: Dict[str, RateLimiter] = {}
        self._lock = asyncio.Lock()
    
    async def acquire(self, host: str, tokens: int = 1, requests_per_minute: Optional[int] = None) -> None:
        """
        Acquire tokens for a specific host.
        
        Args:
            host: The hostname to rate limit
            tokens: Number of tokens to acquire
            requests_per_minute: Custom rate limit for this host
        """
        async with self._lock:
            if host not in self.limiters:
                rpm = requests_per_minute or self.default_requests_per_minute
                self.limiters[host] = RateLimiter(requests_per_minute=rpm)
        
        await self.limiters[host].acquire(tokens)
    
    async def handle_error(self, host: str, error: Exception) -> None:
        """Handle error for specific host."""
        if host in self.limiters:
            await self.limiters[host].handle_error(error)
    
    def handle_success(self, host: str) -> None:
        """Handle success for specific host."""
        if host in self.limiters:
            self.limiters[host].handle_success()
    
    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status for all tracked hosts."""
        return {host: limiter.get_status() for host, limiter in self.limiters.items()}