#!/usr/bin/env python
import datetime
import os
import subprocess
from pathlib import Path

backup_dir = Path('backups')
backup_dir.mkdir(parents=True, exist_ok=True)

ts = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
out_file = backup_dir / f'medical_ops_{ts}.sql'

cmd = [
    'pg_dump',
    os.getenv('PGDATABASE', 'medical_ops'),
    '-h', os.getenv('PGHOST', 'localhost'),
    '-p', os.getenv('PGPORT', '5432'),
    '-U', os.getenv('PGUSER', 'postgres'),
    '-f', str(out_file),
]

subprocess.run(cmd, check=True)
print(f'backup_created={out_file}')
