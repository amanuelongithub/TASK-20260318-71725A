#!/usr/bin/env python
import argparse
import datetime
import os
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--file', required=True)
parser.add_argument('--pre-backup', action='store_true', help='Take a backup before restoring')
args = parser.parse_args()

if args.pre_backup:
    ts = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    pre_file = f"backups/pre_restore_{ts}.sql"
    print(f"Creating pre-restore backup: {pre_file}")
    backup_cmd = [
        'pg_dump',
        os.getenv('PGDATABASE', 'medical_ops'),
        '-h', os.getenv('PGHOST', 'localhost'),
        '-p', os.getenv('PGPORT', '5432'),
        '-U', os.getenv('PGUSER', 'postgres'),
        '-f', pre_file,
    ]
    subprocess.run(backup_cmd, check=True)

cmd = [
    'psql',
    os.getenv('PGDATABASE', 'medical_ops'),
    '-h', os.getenv('PGHOST', 'localhost'),
    '-p', os.getenv('PGPORT', '5432'),
    '-U', os.getenv('PGUSER', 'postgres'),
    '-f', args.file,
]

subprocess.run(cmd, check=True)
print(f'restored_from={args.file}')
