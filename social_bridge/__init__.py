"""Social Bridge: lets an AI agent post, comment and DM across social platforms, with a live oversight dashboard."""
from .base import ADAPTERS, Adapter, Incoming, PlatformError, Result  # noqa: F401
from . import adapters  # noqa: F401  (registers every platform)
from .core import Bridge, Responder  # noqa: F401
