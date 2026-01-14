"""
Middleware for Flask application.

Includes rate limiting and other production middleware.
"""
from functools import wraps
from flask import request, jsonify
import time
from collections import defaultdict
import threading


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self):
        self.requests = defaultdict(list)
        self.lock = threading.Lock()

    def is_allowed(self, key: str, max_requests: int = 10, window: int = 60) -> bool:
        """
        Check if a request is allowed under the rate limit.

        Args:
            key: Unique identifier for the client (e.g., IP address)
            max_requests: Maximum number of requests allowed in the window
            window: Time window in seconds

        Returns:
            True if the request is allowed, False otherwise
        """
        now = time.time()
        with self.lock:
            # Clean old requests outside the window
            self.requests[key] = [t for t in self.requests[key] if now - t < window]

            # Check if limit exceeded
            if len(self.requests[key]) >= max_requests:
                return False

            # Record this request
            self.requests[key].append(now)
            return True

    def reset(self, key: str = None):
        """Reset rate limit for a key or all keys."""
        with self.lock:
            if key:
                self.requests.pop(key, None)
            else:
                self.requests.clear()


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limit(max_requests: int = 10, window: int = 60):
    """
    Decorator to apply rate limiting to a route.

    Args:
        max_requests: Maximum number of requests allowed in the window
        window: Time window in seconds

    Usage:
        @app.route('/api/upload')
        @rate_limit(max_requests=5, window=60)
        def upload():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Use X-Forwarded-For header if behind a proxy, otherwise use remote_addr
            client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            # Take the first IP if there are multiple (proxy chain)
            if client_ip and "," in client_ip:
                client_ip = client_ip.split(",")[0].strip()

            if not rate_limiter.is_allowed(client_ip, max_requests, window):
                return jsonify({
                    "error": "Rate limit exceeded",
                    "message": f"Maximum {max_requests} requests per {window} seconds"
                }), 429

            return f(*args, **kwargs)
        return decorated
    return decorator


def get_client_ip() -> str:
    """Get the client IP address, handling proxies."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "unknown"
