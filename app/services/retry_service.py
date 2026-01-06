"""
Retry Service Module
Handles retry logic and circuit breaker pattern
"""

import asyncio
import time
from enum import Enum
from typing import Callable, Optional
from datetime import datetime, timedelta

from ..config import config
from ..utils.logger import logger


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker implementation"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.half_open_calls = 0
    
    def can_execute(self) -> bool:
        """Check if request can be executed"""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                elapsed = datetime.now() - self.last_failure_time
                if elapsed >= timedelta(seconds=self.recovery_timeout):
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info("Circuit breaker: OPEN -> HALF_OPEN")
                    return True
            return False
        
        if self.state == CircuitState.HALF_OPEN:
            return self.half_open_calls < self.half_open_max_calls
        
        return False
    
    def record_success(self) -> None:
        """Record successful execution"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker: HALF_OPEN -> CLOSED")
        else:
            self.failure_count = 0
    
    def record_failure(self) -> None:
        """Record failed execution"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker: HALF_OPEN -> OPEN")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker: CLOSED -> OPEN (failures: {self.failure_count})")
    
    def get_status(self) -> dict:
        """Get circuit breaker status"""
        return {
            'state': self.state.value,
            'failure_count': self.failure_count,
            'failure_threshold': self.failure_threshold,
            'last_failure': self.last_failure_time.isoformat() if self.last_failure_time else None
        }


class RetryService:
    """Service for retry operations"""
    
    def __init__(self):
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
    
    def get_circuit_breaker(self, name: str) -> CircuitBreaker:
        """Get or create circuit breaker for a service"""
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker(
                failure_threshold=config.circuit_breaker.failure_threshold,
                recovery_timeout=config.circuit_breaker.recovery_timeout
            )
        return self.circuit_breakers[name]
    
    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        service_name: str = "default",
        **kwargs
    ):
        """Execute function with retry and circuit breaker"""
        circuit = self.get_circuit_breaker(service_name)
        
        if not circuit.can_execute():
            raise Exception(f"Circuit breaker is OPEN for {service_name}")
        
        max_attempts = config.retry.max_attempts
        delay = config.retry.initial_delay
        
        for attempt in range(1, max_attempts + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                circuit.record_success()
                return result
                
            except Exception as e:
                circuit.record_failure()
                
                if attempt < max_attempts:
                    logger.warning(f"Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    
                    # Apply backoff strategy
                    if config.retry.strategy == "exponential":
                        delay = min(delay * config.retry.backoff_multiplier, config.retry.max_delay)
                    elif config.retry.strategy == "linear":
                        delay = min(delay + config.retry.initial_delay, config.retry.max_delay)
                else:
                    logger.error(f"All {max_attempts} attempts failed: {e}")
                    raise
    
    def get_all_circuit_status(self) -> dict:
        """Get status of all circuit breakers"""
        return {
            name: cb.get_status() 
            for name, cb in self.circuit_breakers.items()
        }


# Global service instance
retry_service = RetryService()
