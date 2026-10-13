"""Bounded retry with inspectable, non-secret exit receipts."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def retry(command, stage, attempts=3, wait_seconds=10, runner=subprocess.run, sleep=time.sleep):
    results = []
    for attempt in range(attempts):
        print('Check %s: attempt %s/%s' % (stage, attempt + 1, attempts), flush=True)
        try:
            result = runner(command, check=False, timeout=360)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        results.append({'attempt': attempt + 1, 'exitCode': code})
        if code == 0:
            return {'stage': stage, 'success': True, 'attempts': results}
        if attempt + 1 < attempts:
            sleep(wait_seconds * (attempt + 1))
    return {'stage': stage, 'success': False, 'attempts': results}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stage', required=True, choices=['source-fetch', 'source-render', 'publication-readback', 'both-sites'])
    p.add_argument('--attempts', type=int, default=3)
    p.add_argument('--wait-seconds', type=int, default=10)
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not command or not 1 <= a.attempts <= 5 or not 0 <= a.wait_seconds <= 60:
        p.error('Invalid bounded retry configuration')
    result = retry(command, a.stage, a.attempts, a.wait_seconds)
    out = Path('artifacts'); out.mkdir(exist_ok=True)
    (out / ('retry-' + a.stage + '.json')).write_text(json.dumps(result, indent=2))
    raise SystemExit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
