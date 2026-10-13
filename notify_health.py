"""Deduplicated GitHub notifications to this repository's owner only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.request

REPO = 'chenchen1228/a-share-review-archive'
OWNER = 'chenchen1228'
MARKER = '<!-- a-share-health-alert-v1 -->'


def alert_action(issues, failed):
    active = [x for x in issues if MARKER in (x.get('body') or '') and 'pull_request' not in x
              and x.get('user', {}).get('login') == 'github-actions[bot]'
              and OWNER in [a.get('login') for a in x.get('assignees', [])]]
    if failed:
        return ('update', active[0]) if active else ('create', None)
    return ('recover', active) if active else ('quiet', [])


def api(method, path, payload=None):
    token = os.environ.get('GITHUB_TOKEN')
    if not token or os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise RuntimeError('Notification requires this repository runner and its temporary token')
    request = urllib.request.Request('https://api.github.com/repos/' + REPO + path,
        data=None if payload is None else json.dumps(payload).encode(), method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json',
                 'User-Agent': 'AshareHealthAlert/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def open_alerts():
    for page in range(1, 21):
        rows = api('GET', '/issues?state=open&per_page=100&page=' + str(page))
        for row in rows:
            if alert_action([row], True)[0] == 'update':
                yield row
        if len(rows) < 100:
            return
    raise RuntimeError('Issue pagination exceeded the supported notification limit')


def details():
    failures = []
    for path in Path('artifacts').glob('retry-*.json'):
        value = json.loads(path.read_text())
        if not value.get('success'):
            failures.append(value['stage'])
    # Publish stage names and public run links only, never raw logs or tokens.
    phase = ', '.join(sorted(failures)) or 'workflow/deployment'
    run = os.environ['GITHUB_RUN_ID']
    return phase, 'https://github.com/' + REPO + '/actions/runs/' + run


def notify(failed):
    phase, run = details()
    action, active = alert_action(list(open_alerts()), failed)
    if action == 'quiet':
        return {'action': 'quiet', 'reason': 'All checks passed; no active alert'}
    if action == 'recover':
        for issue in active:
            number = str(issue['number'])
            api('POST', '/issues/' + number + '/comments', {'body': '自动复查已恢复：源站、GitHub网页、日期切换及历史归档均通过。\n\n[本次验收记录](' + run + ')'})
            api('PATCH', '/issues/' + number, {'state': 'closed', 'state_reason': 'completed'})
        return {'action': 'recovered', 'issues': [x['number'] for x in active]}
    fingerprint = hashlib.sha256(phase.encode()).hexdigest()
    stamp = datetime.now(timezone.utc).isoformat()
    body = MARKER + '\n<!-- failure:' + fingerprint + ' -->\n\n@' + OWNER + ' 自动巡检在重试后仍未通过。\n\n'
    body += '- 检查阶段：`' + phase + '`\n- 检查时间（UTC）：' + stamp + '\n'
    body += '- [失败任务与截图/验收回执](' + run + ')\n\n'
    body += '同步仅在源站页面通过后发布；现有网站与历史档案不会被清空。后续定时任务继续复查，恢复后会关闭这条告警。'
    if action == 'create':
        issue = api('POST', '/issues', {'title': '[自动巡检] A股复盘更新验收失败', 'body': body, 'assignees': [OWNER]})
        return {'action': 'created', 'issue': issue['number'], 'url': issue['html_url']}
    number = str(active['number'])
    if '<!-- failure:' + fingerprint + ' -->' not in (active.get('body') or ''):
        api('POST', '/issues/' + number + '/comments', {'body': '@' + OWNER + ' 故障阶段有变化：`' + phase + '`。\n\n[最新任务](' + run + ')'})
    api('PATCH', '/issues/' + number, {'body': body})
    return {'action': 'updated-existing-alert', 'issue': active['number']}


def exercise():
    # Explicit workflow_dispatch opt-in only. Clearly label this notification
    # exercise; it never marks a healthy report as a real failure.
    run = 'https://github.com/' + REPO + '/actions/runs/' + os.environ['GITHUB_RUN_ID']
    issue = api('POST', '/issues', {'title': '[巡检演练] A股复盘提醒链路测试',
        'body': '@' + OWNER + ' 这是安装后的通知演练，并非真实网站故障。\n\n测试通知创建、指派给本人和自动恢复关闭。\n\n[演练记录](' + run + ')',
        'assignees': [OWNER]})
    number = str(issue['number'])
    try:
        api('POST', '/issues/' + number + '/comments', {'body': '演练通过：通知已创建并指派，自动恢复关闭链路正在完成；未修改报告或历史数据。'})
    finally:
        api('PATCH', '/issues/' + number, {'state': 'closed', 'state_reason': 'completed'})
    return {'action': 'notification-exercise-completed', 'issue': issue['number'], 'url': issue['html_url']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('outcome', choices=['success', 'failure', 'exercise']); a = p.parse_args()
    result = exercise() if a.outcome == 'exercise' else notify(a.outcome == 'failure')
    print(json.dumps(result, ensure_ascii=False))
