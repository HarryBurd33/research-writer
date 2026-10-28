#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check a copied install from an unrelated working directory; no network."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--molecular', action='store_true')
    parser.add_argument('--skill', type=Path, default=ROOT / 'skills' / 'research-writer')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='research-writer-package-') as directory:
        root = Path(directory)
        skill = root / 'installed' / 'research-writer'
        shutil.copytree(args.skill, skill, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.skill-forge-managed.json'))
        work = root / 'unrelated'
        work.mkdir()
        command = [sys.executable, str(skill / 'scripts' / 'self_check.py')]
        if args.molecular:
            command.append('--molecular')
        def run():
            return subprocess.run(command, cwd=work, text=True, capture_output=True, timeout=180,
                                  env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        result = run()
        if result.returncode:
            print(result.stdout + result.stderr)
            return 1
        report = json.loads(result.stdout)
        if not report.get('passed'):
            raise ValueError('Installed check did not pass')
        # A command-only copy might work but lacks its independently required
        # catalog. This negative control must fail before any functional checks.
        (skill / 'references' / 'tool-catalog.json').unlink()
        negative = run()
        rejected = json.loads(negative.stdout)
        if negative.returncode != 1 or rejected.get('passed') is not False or 'tool-catalog.json' not in rejected.get('error', ''):
            raise ValueError('Missing-resource negative control failed')
        print(json.dumps({'passed': True, 'installed': report, 'missing_resource_rejected': True,
                          'scope': 'copied folder from unrelated cwd; selected interpreter only'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
