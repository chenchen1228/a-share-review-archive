"""Plan and verify Pages publication against the reviewed local mirror.

Separate repository sync from deployment: a previous failed Pages deployment
must remain eligible even when the repository already has the latest data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

SITE = 'https://chenchen1228.github.io/a-share-review-archive/'
FIELDS = ('artifactId', 'sourceHtmlSha256', 'snapshotSha256', 'generatedAt',
          'reportDates', 'queryCount', 'rowCount', 'mirrorHtmlSha256')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fetch(path):
    # A new query distinguishes a verification from an intermediary's stale cache.
    url = SITE + path + '?sync_verify=' + str(time.time_ns())
    request = urllib.request.Request(url, headers={'User-Agent': 'AsharePagesVerification/1.0', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=25) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != 'https' or final.netloc != 'chenchen1228.github.io':
            raise ValueError('Unexpected Pages redirect')
        result = response.read(80 * 1024 * 1024 + 1)
        if len(result) > 80 * 1024 * 1024:
            raise ValueError('Unexpectedly large public artifact')
        return result


def expected(directory):
    root = Path(directory)
    manifest = json.loads((root / 'mirror-manifest.json').read_text())
    html = (root / 'index.html').read_bytes()
    snapshot = (root / 'snapshot.json').read_bytes()
    if sha(html) != manifest['mirrorHtmlSha256'] or sha(snapshot) != manifest['snapshotSha256']:
        raise ValueError('Local mirror files disagree with their manifest')
    if not manifest['reportDates']:
        raise ValueError('Empty archive')
    return manifest


def check(directory, download=fetch):
    local = expected(directory)
    remote = json.loads(download('mirror-manifest.json'))
    mismatched = [f for f in FIELDS if remote.get(f) != local.get(f)]
    if mismatched:
        return {'matches': False, 'reason': 'published manifest differs', 'fields': mismatched}
    for path, field in [('index.html', 'mirrorHtmlSha256'), ('snapshot.json', 'snapshotSha256')]:
        if sha(download(path)) != local[field]:
            return {'matches': False, 'reason': path + ' bytes differ'}
    # The current complete dataset is archived under its immutable content hash.
    archived = 'history/snapshot-' + local['reportDates'][-1] + '-' + local['snapshotSha256'][:16] + '.json'
    if sha(download(archived)) != local['snapshotSha256']:
        return {'matches': False, 'reason': 'published history does not match'}
    return {'matches': True, 'reportDates': local['reportDates'], 'generatedAt': local['generatedAt'],
            'snapshotSha256': local['snapshotSha256'], 'mirrorHtmlSha256': local['mirrorHtmlSha256'],
            'queryCount': local['queryCount'], 'rowCount': local['rowCount'], 'historyVerified': True}


def plan(directory, download=fetch):
    expected(directory)  # A malformed local artifact stops publication.
    try:
        result = check(directory, download)
        return {'needs_deploy': not result['matches'], 'verification': result}
    except (OSError, ValueError, KeyError) as error:
        return {'needs_deploy': True, 'verification': {'matches': False, 'reason': type(error).__name__}}


def verify(directory, attempts=8, wait_seconds=5, download=fetch):
    result = None
    for attempt in range(attempts):
        try:
            result = check(directory, download)
        except (OSError, ValueError, KeyError) as error:
            result = {'matches': False, 'reason': type(error).__name__}
        if result['matches']:
            return result
        if attempt + 1 < attempts:
            time.sleep(wait_seconds)
    raise RuntimeError('Pages publication readback failed: ' + json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['plan', 'verify'])
    parser.add_argument('--directory', default='docs')
    parser.add_argument('--attempts', type=int, default=8)
    parser.add_argument('--wait-seconds', type=int, default=5)
    args = parser.parse_args()
    result = plan(args.directory) if args.mode == 'plan' else verify(args.directory, args.attempts, args.wait_seconds)
    print(json.dumps(result, ensure_ascii=False))
    if args.mode == 'plan' and os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('needs_deploy=' + str(result['needs_deploy']).lower() + '\n')
    if args.mode == 'verify' and os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('### Public report and history verified\n\n')
            summary.write('Updated: ' + str(result['generatedAt']) + '\n\n')
            summary.write('Archived dates: ' + ', '.join(result['reportDates']) + '\n\n')
            summary.write('Snapshot SHA-256: `' + result['snapshotSha256'] + '`\n\n')
            summary.write('Public HTML, snapshot and immutable history all match the reviewed files.\n')


if __name__ == '__main__':
    main()
