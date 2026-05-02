"""Logging package — single import point for service startup events.

Usage in every service's startup event:
    from backend.logging import LogSetupFactory
    LogSetupFactory.create(settings.environment).configure("ingestion")

That one call sets up all handlers, formatters, and log levels
for the current environment (dev → file+stdout, prod → CloudWatch).
"""
from backend.logging.factory import LogSetupFactory

__all__ = ["LogSetupFactory"]
