"""Reject private/runtime files using tracked paths or a PR's changed paths."""
from pathlib import Path, PurePosixPath
import argparse
import subprocess

def forbidden(name: str) -> bool:
    path = PurePosixPath(name)
    if any(p.lower() in {'.runtime', '.venv', 'node_modules', 'backups', '.workbuddy', 'outputs_wb'} for p in path.parts):
        return True
    if name.startswith(('backend/storage/', 'backend/devdata/')):
        return True
    if path.name.startswith('.env') and not path.name.endswith('.example'):
        return True
    return path.name.lower().endswith(('.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3', '.dump', '.pem', '.pfx', '.key', '.doc', '.docx'))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default='.')
    parser.add_argument('--base')
    parser.add_argument('--scope-file')
    args = parser.parse_args()
    command = ['git', '-C', args.repo]
    names = subprocess.check_output(command + ['ls-files', '-z']).decode().split('\0')
    rejected = [n for n in names if n and forbidden(n)]
    if rejected:
        print('Private files tracked: ' + ', '.join(rejected)); return 1
    if args.base:
        changed = subprocess.check_output(command + ['diff', '--name-only', '-z', args.base + '...HEAD']).decode().split('\0')
        if args.scope_file:
            scope = [line.strip() for line in Path(args.scope_file).read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')]
            outside = [n for n in changed if n and not any(n == s or (s.endswith('/') and n.startswith(s)) for s in scope)]
            if outside:
                print('Changes outside agreed scope: ' + ', '.join(outside)); return 1
    print('Tracked-file boundary passed. Secret content is checked separately by Gitleaks.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
