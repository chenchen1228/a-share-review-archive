"""Check data freshness, rendered pages, date navigation and immutable archives.

Run browsers only in the unattended GitHub runner. No user browser session,
private account data, or local machine is required.
"""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import urllib.request
from zoneinfo import ZoneInfo

from sync_public_site import ORIGIN, ARTIFACT, read_verified_pair
from verify_publication import SITE, check as check_publication


def digest(value):
    return hashlib.sha256(value).hexdigest()


def required_session(bars, now):
    # The 08:30 run has until 10:00 Beijing to finish. Weekend checks use the
    # latest weekday morning; holidays are resolved from actual trading bars.
    anchor = now.astimezone(ZoneInfo('Asia/Shanghai'))
    if (anchor.hour, anchor.minute) < (10, 0):
        anchor -= timedelta(days=1)
    while anchor.weekday() >= 5:
        anchor -= timedelta(days=1)
    dates = []
    for bar in bars:
        day = str(bar.get('day', ''))[:10]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            raise ValueError('Invalid trading calendar observation')
        if day < anchor.date().isoformat():
            dates.append(day)
    if not dates:
        raise ValueError('Cannot establish the expected completed session')
    return max(dates)


def read_calendar(now, fetch=None, include_sessions=False):
    endpoints = [
        'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/CN_MarketDataService.getKLineData?symbol=sh000001&scale=240&ma=no&datalen=1023',
        'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000001&scale=240&ma=no&datalen=1023',
    ]
    def download(url):
        req = urllib.request.Request(url, headers={'User-Agent': 'AshareHealthCheck/1.0'})
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read(2 * 1024 * 1024).decode('utf-8')
    for url in endpoints:
        try:
            raw = (fetch or download)(url)
            match = re.search(r'(\[.*\])', raw, flags=re.S)
            bars = json.loads(match.group(1)) if match else json.loads(raw)
            if not isinstance(bars, list) or len(bars) < 10:
                raise ValueError('Incomplete calendar history')
            for bar in bars:
                if not all(float(bar[k]) > 0 for k in ('open', 'high', 'low', 'close')):
                    raise ValueError('Invalid calendar price')
            target = required_session(bars, now)
            if include_sessions:
                return {'required': target, 'sessions': sorted({str(b['day'])[:10] for b in bars if str(b['day'])[:10] <= target})}
            return target
        except (OSError, ValueError, TypeError, KeyError):
            continue
    raise RuntimeError('Both public trading-calendar paths failed; freshness is unverified')


def validate_snapshot(snapshot, target, required_dates=None):
    if snapshot.get('id') != ARTIFACT or snapshot.get('buildStatus') != 'complete':
        raise ValueError('Wrong artifact or incomplete report')
    rows = snapshot.get('queries', {}).get('reports', {}).get('rows', [])
    dates = [r.get('review_date') for r in rows]
    if not dates or len(set(dates)) != len(dates) or target not in dates:
        raise ValueError('Expected review is missing or historical dates are duplicated')
    if required_dates is not None:
        if not required_dates or min(required_dates) > min(dates):
            raise ValueError('Trading-calendar coverage does not reach the first archived review')
        missing = [d for d in required_dates if min(dates) <= d <= target and d not in dates]
        if missing:
            raise ValueError('Missing trading-day archives: ' + ', '.join(missing))
    for report in rows:
        day = report['review_date']
        if len(report.get('visuals', {}).get('conclusions', [])) != 12:
            raise ValueError('Missing module conclusions: ' + day)
        indicators = [x for x in snapshot['queries'].get('indicator_table', {}).get('rows', []) if x.get('review_date') == day]
        if len(indicators) != 14:
            raise ValueError('Missing indicator rows: ' + day)
    return sorted(dates)


def browser_check(url, snapshot, label, out):
    from playwright.sync_api import sync_playwright, expect
    reports = sorted(snapshot['queries']['reports']['rows'], key=lambda r: r['review_date'])
    latest = reports[-1]
    errors = []
    checks = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.set_default_timeout(45000)
            page.on('pageerror', lambda error: errors.append(str(error).split('\n')[0][:250]))
            response = page.goto(url + '?view=1&tab=overview', wait_until='domcontentloaded', timeout=60000)
            if not response or response.status != 200:
                raise ValueError(label + ' homepage failed')
            expect(page.get_by_role('heading', name=latest['title'], exact=True)).to_be_visible()
            checks.append('overview')
            page.get_by_role('tab', name='完整报告', exact=True).click()
            expect(page.locator('section.v-section')).to_have_count(12)
            expect(page.get_by_role('heading', name=latest['title'], exact=True)).to_be_visible()
            checks.append('12 full-report sections')
            page.get_by_role('tab', name='数据来源', exact=True).click()
            expect(page.get_by_role('heading', name='数据如何获取', exact=True)).to_be_visible()
            checks.append('sources')
            page.get_by_role('tab', name='历史档案', exact=True).click()
            expect(page.get_by_role('heading', name='历史档案', exact=True)).to_be_visible()
            checks.append('archive')
            page.get_by_role('tab', name='复盘总览', exact=True).click()
            # Check the oldest retained date and the previous report, not just
            # calendar button existence. Each must actually render its title.
            for report in [reports[0], reports[-2] if len(reports) > 1 else latest, latest]:
                page.get_by_role('button', name=report['review_date'] + ' 已归档', exact=True).click()
                expect(page.get_by_role('heading', name=report['title'], exact=True)).to_be_visible()
                checks.append('date ' + report['review_date'])
            if errors:
                raise ValueError(label + ' browser pageerror: ' + '; '.join(errors))
            page.screenshot(path=str(out / ('site-' + label + '.png')))
            return {'site': label, 'rendered': True, 'checks': checks, 'pageErrors': errors}
        except Exception:
            page.screenshot(path=str(out / ('site-' + label + '-failure.png')))
            raise
        finally:
            browser.close()


def archived_revisions(directory):
    paths = sorted((Path(directory) / 'history').glob('snapshot-*.json'))
    if not paths:
        raise ValueError('Immutable archive is empty')
    # Full current snapshot verification covers every historical report row.
    # Independently retain/read the oldest immutable revision as well.
    path = paths[0]
    req = urllib.request.Request(SITE + 'history/' + path.name, headers={'User-Agent': 'AshareArchiveCheck/1.0'})
    with urllib.request.urlopen(req, timeout=30) as response:
        if digest(response.read()) != digest(path.read_bytes()):
            raise ValueError('Old immutable archive was lost or modified')
    return {'oldestImmutableRevision': path.name, 'retainedRevisionCount': len(paths)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scope', choices=['source', 'both'], default='both')
    p.add_argument('--directory', default='docs')
    p.add_argument('--expected-date')
    a = p.parse_args()
    out = Path('artifacts'); out.mkdir(exist_ok=True)
    local = json.loads((Path(a.directory) / 'snapshot.json').read_text())
    calendar = None if a.expected_date else read_calendar(datetime.now(ZoneInfo('Asia/Shanghai')), include_sessions=True)
    target = a.expected_date or calendar['required']
    required_dates = None if calendar is None else calendar['sessions']
    dates = validate_snapshot(local, target, required_dates)
    source_html, source_bytes, source = read_verified_pair()
    if digest(source_bytes) != digest((Path(a.directory) / 'snapshot.json').read_bytes()):
        raise ValueError('Source changed during the check; retry against a consistent version')
    validate_snapshot(source, target, required_dates)
    result = {'expectedReviewDate': target, 'reportDates': dates, 'sourceSha256': digest(source_bytes), 'sites': []}
    result['sites'].append(browser_check(ORIGIN + '/', source, 'source', out))
    if a.scope == 'both':
        publication = check_publication(a.directory)
        if not publication['matches']:
            raise ValueError('Published mirror or archive differs from the reviewed source')
        result['publication'] = publication
        result['archives'] = archived_revisions(a.directory)
        result['sites'].append(browser_check(SITE, local, 'github', out))
    (out / ('health-' + a.scope + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
