import re

files_to_migrate = [
    r'd:\CX-O\CXHMS\backend\api\routers\chat.py',
    r'd:\CX-O\CXHMS\backend\api\routers\context.py',
    r'd:\CX-O\CXHMS\backend\api\routers\memory_chat.py',
    r'd:\CX-O\CXHMS\backend\api\routers\admin.py',
    r'd:\CX-O\CXHMS\backend\api\routers\archive.py',
]

for file_path in files_to_migrate:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

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
            (r'memory_id = memory_mgr\.', 'memory_id = await memory_mgr.'),
        ]

        for pat, repl in patterns:
            content = re.sub(pat, repl, content)

        content = content.replace('conn.close()', 'await conn.close()')
        content = content.replace('cursor = conn.cursor()', 'cursor = await conn.execute(')
        content = content.replace('cursor.execute(', 'cursor = await conn.execute(')
        content = content.replace('cursor.fetchone()', 'await cursor.fetchone()')
        content = content.replace('cursor.fetchall()', 'await cursor.fetchall()')

        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f'Migrated: {file_path}')
        else:
            print(f'Skipped (no changes): {file_path}')

    except FileNotFoundError:
        print(f'Not found: {file_path}')
    except Exception as e:
        print(f'Error processing {file_path}: {e}')

print('Done')
