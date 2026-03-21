import os
import re

file_path = r'd:\CX-O\CXHMS\backend\api\routers\context.py'

try:
    if not os.path.exists(file_path):
        print(f'Not found: {file_path}')
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # Add get_memory_manager function if not exists
        if 'def get_memory_manager():' not in content:
            # Find first import line
            match = re.search(r'(from backend\.api\.app import[^\n]+\n)(router = )', content)
            if match:
                insert_pos = match.start(2)
                func_def = '''

def get_memory_manager():
    from backend.api.app import get_async_memory_manager
    return get_async_memory_manager()

'''
                content = content[:insert_pos] + func_def + content[insert_pos:]

        # Replace patterns - handle both memory_mgr and memory_manager
        patterns = [
            (r'memories = memory_mgr\.', 'memories = await memory_mgr.'),
            (r'memories = memory_manager\.', 'memories = await memory_manager.'),
            (r'results = memory_mgr\.', 'results = await memory_mgr.'),
            (r'results = memory_manager\.', 'results = await memory_manager.'),
            (r'memory = memory_mgr\.', 'memory = await memory_mgr.'),
            (r'memory = memory_manager\.', 'memory = await memory_manager.'),
            (r'memory_id = memory_mgr\.', 'memory_id = await memory_mgr.'),
            (r'memory_id = memory_manager\.', 'memory_id = await memory_manager.'),
            (r'summary_memory_id = memory_manager\.', 'summary_memory_id = await memory_manager.'),
            (r'result = memory_mgr\.', 'result = await memory_mgr.'),
            (r'result = memory_manager\.', 'result = await memory_manager.'),
        ]

        for pat, repl in patterns:
            content = re.sub(pat, repl, content)

        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f'Migrated: {file_path}')
        else:
            print(f'Skipped: {file_path}')

except Exception as e:
    print(f'Error: {e}')

print('Done')
