#!/usr/bin/env python3
"""Keeps only the newest release on GitHub (the user, 2026-11-05: nobody should download an old version, only the
current one). Run it straight after a new release is published:

    python3 tools/prune_releases.py            # lists what it would delete
    python3 tools/prune_releases.py --delete   # deletes every release but the latest, with its tag

The repo is this clone's GitHub repo. It never deletes the latest release, and does nothing if GitHub can't say which
that is. The deleted tags also go from this clone, so a later "git push --tags" doesn't bring them back. The apps'
update checks ask for releases/latest, so nothing needs the old ones. (The same file is in SkyScope, the SkyScope
Mini and Satellite, and Train Tracker; Aviator Trail has its own.)
Designed and Created by Project Moon Pi.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gh(*args):
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True, cwd=ROOT).stdout


def main():
    repo = json.loads(gh('repo', 'view', '--json', 'nameWithOwner'))['nameWithOwner']
    latest = json.loads(gh('release', 'view', '-R', repo, '--json', 'tagName'))['tagName']
    if not latest:
        sys.exit(f'{repo}: no latest release, so nothing was deleted')
    tags = [r['tagName'] for r in json.loads(gh('release', 'list', '-R', repo, '--limit', '200', '--json', 'tagName'))]
    old = [t for t in tags if t != latest]
    print(f'{repo}: keeping {latest}; older: {", ".join(old) or "none"}')
    if '--delete' not in sys.argv:
        return
    for t in old:
        gh('release', 'delete', t, '-R', repo, '--yes', '--cleanup-tag')
        print(f'  deleted {t}')
    # and this clone's copies of every tag but the latest (tags with no release too), so a push doesn't bring them back
    local = subprocess.run(['git', 'tag'], capture_output=True, text=True, cwd=ROOT).stdout.split()
    gone = [t for t in local if t != latest and t.startswith('v')]
    if gone:
        subprocess.run(['git', 'tag', '-d', *gone], capture_output=True, cwd=ROOT)
        print(f'  removed from this clone: {", ".join(gone)}')


if __name__ == '__main__':
    main()
