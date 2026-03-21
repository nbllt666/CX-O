import re


with open(r'd:\CX-O\CXHMS\backend\api\routers\memory.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.exceptions import MemoryOperationError
from backend.core.logging_config import get_contextual_logger
from backend.core.memory.secondary_router import SecondaryInstruction

router = APIRouter()
logger = get_contextual_logger(__name__)'''

new = '''from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.exceptions import MemoryOperationError
from backend.core.logging_config import get_contextual_logger
from backend.core.memory.secondary_router import SecondaryInstruction


def get_memory_manager():
    from backend.api.app import get_async_memory_manager
    return get_async_memory_manager()


router = APIRouter()
logger = get_contextual_logger(__name__)'''

content = content.replace(old, new)

patterns = [
    (r'memories = memory_mgr\.', 'memories = await memory_mgr.'),
    (r'results = memory_mgr\.', 'results = await memory_mgr.'),
    (r'stats = memory_mgr\.', 'stats = await memory_mgr.'),
    (r'memory = memory_mgr\.', 'memory = await memory_mgr.'),
    (r'result = memory_mgr\.', 'result = await memory_mgr.'),
    (r'success = memory_mgr\.', 'success = await memory_mgr.'),
    (r'enabled = memory_mgr\.', 'enabled = await memory_mgr.'),
    (r'if memory_mgr\.', 'if await memory_mgr.'),
    (r'conn = memory_mgr\.', 'conn = await memory_mgr.'),
]

for pat, repl in patterns:
    content = re.sub(pat, repl, content)

content = content.replace('conn.close()', 'await conn.close()')
content = content.replace('cursor = conn.cursor()', 'cursor = await conn.execute(')
content = content.replace('cursor.execute(', 'cursor = await conn.execute(')
content = content.replace('cursor.fetchone()', 'await cursor.fetchone()')
content = content.replace('cursor.fetchall()', 'await cursor.fetchall()')

with open(r'd:\CX-O\CXHMS\backend\api\routers\memory.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')
