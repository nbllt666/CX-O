"""Shared utilities for MemoryManager mixins.

Extracted from the original manager.py module-level definitions.
All mixins import json_dumps, json_loads, and logger from here.
"""

from typing import TYPE_CHECKING

from server.core.logging_config import get_contextual_logger

if TYPE_CHECKING:
    pass

try:
    import orjson

    def json_dumps(obj, **kwargs):
        return orjson.dumps(obj).decode("utf-8")

    def json_loads(s, **kwargs):
        return orjson.loads(s)

except ImportError:
    import json

    def json_dumps(obj, **kwargs):
        return json.dumps(obj, **kwargs)

    def json_loads(s, **kwargs):
        return json.loads(s, **kwargs)


logger = get_contextual_logger(__name__)
