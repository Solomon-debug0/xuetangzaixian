"""Ordered course workflow: resumable breakpoints and auditable AI handoffs.

scan only reads the live directory. run processes the earliest unfinished item,
persisting every transition so a restart never repeats a publication or a
submission. Failures are persisted with a reason instead of vanishing.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Error as PlaywrightError

from dsh_question import REPORTS, make_request
from homework_dom import HOMEWORK_ROOT
from inspect_course import inspect_page
from browser_checks import wait_for_manual_verification
from user_prompts import choose_runtime_seconds

VIDEO_RATE = float(os.environ.get('XT_VIDEO_RATE') or 1)
STATE_FILE = REPORTS / 'workflow_state.json'
REPLY_SELECTOR = 'textarea[placeholder="发表你的观点"]'
KIND_LABELS = {'video': '视频', 'article': '图文', 'discussion': '讨论', 'homework': '作业', 'unknown': '未知类型'}


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def next_task(tasks, kinds=None):
    return next((t for t in tasks
                 if t['status'] != 'completed' and (not kinds or t['kind'] in kinds)), None)


def request_digest(request):
    """Stable identity: execution snapshot never takes part in the fingerprint."""
    clean = {k: v for k, v in request.items() if k not in ('request_id', 'state_snapshot')}
    return hashlib.sha256(json.dumps(clean, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def checked_reply(request, response):
    if response.get('kind') != 'discussion' or response.get('request_id') != request['request_id']:
        raise ValueError('讨论回复与请求不匹配。')
    reply = response.get('reply')
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 4000:
        raise ValueError('讨论回复为空或过长。')
    return reply.strip()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def directory(page):
    """Read the live directory; never trust a cached list from an earlier run."""
    page.wait_for_function("document.querySelector('.course-action-lesson-left')?.__vue__?.$data?.listName?.length > 0", timeout=20000)
    result = inspect_page(page)
    if not result['directory_found']:
        raise ValueError('目录未加载，已停止。')
    if not result['tasks']:
        raise ValueError('目录为空，已停止。')
    return result['tasks']


def guard(page, leaf_id):
    if urlparse(page.url).path.split('/')[-1] != str(leaf_id):
        raise ValueError('网页切换到了其他任务，停止执行。')


def own_nickname(page):
    """Account name shown by the site header; used to confirm our own comment."""
    text = page.evaluate("() => document.querySelector('.user-name')?.innerText || ''")
    match = re.search(r'Hi\s*[～~]\s*(\S+)', text)
    if not match:
        raise ValueError('未检测到登录账号，可能已掉线，已停止。')
    return match.group(1)


def homework_items(page):
    page.wait_for_function("root => document.querySelector(root)?.__vue__?.$data?.prictice?.length > 0",
                           arg=HOMEWORK_ROOT, timeout=20000)
    return page.evaluate(r'''root => {
        const d = document.querySelector(root).__vue__.$data;
        const clean = html => new DOMParser().parseFromString(html || '', 'text/html').body.textContent.replace(/\s+/g, ' ').trim();
        return d.prictice.map((x, index) => ({
            index, problem_id: x.problem_id, submitted: x.user.my_count > 0,
            question: {type: ({1:'single_choice',2:'multiple_choice',6:'judge'})[x.type] || 'unknown',
                text: clean(x.content.Body),
                options: x.type === 6 && !(x.content.Options || []).length
                    ? [{label:'true',text:'正确'},{label:'false',text:'错误'}]
                    : (x.content.Options || []).map(o => ({label: o.key, text: clean(o.value) || (o.key === 'true' ? '正确' : o.key === 'false' ? '错误' : '')})),
                has_images: /<img/i.test(JSON.stringify(x.content)),
                has_math: /<math|katex|MathJax/i.test(JSON.stringify(x.content))}
        }));
    }''', HOMEWORK_ROOT)


def prepare_ai(page, task):
    """Build the DSH request. Question content is stable; submission state is separate."""
    request = {'kind': task['kind'], 'leaf_id': task['id'], 'path': urlparse(page.url).path}
    if task['kind'] == 'discussion':
        page.wait_for_selector(REPLY_SELECTOR, timeout=20000)
        request['topic'] = page.evaluate(r'''() => {
            const c = document.querySelector('.lesson_right')?.__vue__?.$data?.content;
            const doc = new DOMParser().parseFromString(c?.content_info?.context || '', 'text/html');
            return doc.body.textContent.replace(/\s+/g, ' ').trim();
        }''')
        if not request['topic']:
            raise ValueError('讨论主题未读取到。')
    else:
        items = homework_items(page)
        request['items'] = []
        for item in items:
            entry = {'index': item['index'], 'problem_id': item['problem_id'], 'question': item['question']}
            try:
                entry['request'] = make_request({'question': item['question']})
                entry['unsupported'] = None
            except ValueError as exc:
                entry['request'] = None
                entry['unsupported'] = str(exc)
            request['items'].append(entry)
        request['state_snapshot'] = [{'index': i['index'], 'problem_id': i['problem_id'],
                                      'submitted': i['submitted']} for i in items]
    request['request_id'] = request_digest(request)
    return request


def reply_visible(page, reply):
    """Look for our exact reply in the discussion list (own publication evidence)."""
    prefix = re.sub(r'\s+', '', reply)[:100]
    return page.evaluate(r'''text => {
        const norm = s => String(s || '').replace(/\s+/g, '');
        for (const c of document.querySelectorAll('.comment-wrapper')) {
            const body = norm(c.querySelector('.comment-text')?.innerText);
            if (body && body.includes(text)) return {
                nickname: (c.querySelector('.nickname-label')?.innerText || '').trim(),
                published_at: (c.querySelector('.publish-time')?.innerText || '').replace(/\s+/g, ' ').trim()
            };
        }
        return null;
    }''', prefix)


def wait_reply_visible(page, reply, timeout_ms):
    limit = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < limit:
        found = reply_visible(page, reply)
        if found:
            return found
        page.wait_for_timeout(500)
    return None


def publish_discussion(page, task, reply, saved, statefile):
    """Fill, persist sending, publish, then prove the reply appears in the list."""
    history = saved['history'].setdefault(str(task['id']), {})
    seen = reply_visible(page, reply)
    if seen:
        history.update({'publish_evidence': seen, 'verified_at': now()})
        return {**seen, 'already_published': True}
    if history.get('status') == 'sending':
        raise ValueError('上次发送结果不明，讨论列表未见该回复；请人工核对后再恢复，避免重复发布。')
    editor = page.locator(REPLY_SELECTOR)
    if editor.count() != 1:
        raise ValueError('找不到唯一的讨论编辑器，未发布。')
    editor.fill(reply)
    if editor.input_value() != reply:
        raise ValueError('编辑器内容与回复不一致，未发布。')
    history.update({'status': 'sending', 'sending_at': now(), 'reply': reply})
    saved['updated_at'] = now()
    write_json(statefile, saved)
    page.wait_for_function("() => { const b = document.querySelector('.prompt-send-btn'); return b && !b.classList.contains('disabled'); }", timeout=15000)
    send = page.locator('.prompt-send-btn')
    if send.count() != 1:
        raise ValueError('发布按钮不唯一，未发布。')
    send.click()
    page.wait_for_function('sel => document.querySelector(sel)?.value === ""', arg=REPLY_SELECTOR, timeout=20000)
    evidence = wait_reply_visible(page, reply, 30000)
    if not evidence:
        raise ValueError('已点击发布但讨论列表未出现该回复；状态保持 sending，请核对平台后处理。')
    history.update({'publish_evidence': evidence, 'verified_at': now()})
    saved['updated_at'] = now()
    write_json(statefile, saved)
    return evidence


def select_playback_rate(page):
    """Pick a playback speed.

    The player silently ignores the menu selection for this course (it snaps back
    to 1.00X), so when XT_VIDEO_RATE>1 we pin the media clock instead. It stays
    off by default because 2x progress has not been confirmed as platform-credited.
    """
    target = VIDEO_RATE
    if target <= 1:
        return 1.0
    rate = 1.0
    try:
        speed = page.locator('xt-speedvalue').first
        speed.click(timeout=3000)
        page.locator('li', has_text=f'{target:.2f}X').first.click(timeout=3000)
        page.wait_for_timeout(400)
        if f'{target:.2f}' in speed.inner_text(timeout=2000):
            rate = target
    except PlaywrightError:
        rate = 1.0
    if rate <= 1:
        page.evaluate("""(rate) => {
            const v = document.querySelector('video'); if (!v) return;
            try { Object.defineProperty(v, 'playbackRate', {configurable: true, get: () => rate, set: () => {}}); } catch (e) {}
        }""", target)
        rate = target
    print(f"播放倍速：{rate:g}x", flush=True)
    return rate


def handle_video(page, task, deadline):
    wait_for_manual_verification(page,deadline)
    page.wait_for_selector('video', state='attached', timeout=20000)
    rate = select_playback_rate(page)
    last_time = None
    last_progress = time.monotonic()
    while time.monotonic() < deadline:
        guard(page, task['id'])
        wait_started=time.monotonic()
        wait_for_manual_verification(page,deadline)
        # Manual interaction is not a stalled player; start a fresh stall window.
        if time.monotonic()-wait_started>1:
            last_progress=time.monotonic()
        media = page.evaluate('''async (rate) => {
            const v = document.querySelector('video'); if (!v) return null;
            v.playbackRate = rate;
            if (v.paused && !v.ended) { try { await v.play(); } catch (e) { return {blocked: true}; } }
            return {time: v.currentTime, ended: v.ended, error: !!v.error};
        }''', rate)
        if not media or media.get('blocked') or media.get('error'):
            raise ValueError('视频无法正常播放，请检查播放器。')
        if media['ended']:
            return
        if media['time'] != last_time:
            last_progress = time.monotonic()
            last_time = media['time']
        if time.monotonic() - last_progress > 90:
            raise ValueError('视频播放超过90秒没有推进，已暂停。')
        page.wait_for_timeout(1000)
    raise ValueError('本次运行时间到，已保存视频任务断点。')


def read_attachment(page, task):
    """Open each attachment in its own viewer and page through it before marking read."""
    links = page.locator('a.attachment-preview')
    for index in range(links.count()):
        guard(page, task['id'])
        with page.context.expect_page(timeout=20000) as opened:
            links.nth(index).click()
        viewer = opened.value
        viewer.wait_for_load_state('domcontentloaded')
        viewer.wait_for_timeout(1500)
        for _ in range(8):
            try:
                viewer.keyboard.press('PageDown')
            except PlaywrightError:
                break
            viewer.wait_for_timeout(1200)
        viewer.close()


def handle_article(page, task):
    """The reader declares completion with 标记看完; the control only unlocks after reading."""
    page.wait_for_selector('.defen_xtb', timeout=20000)
    if '未阅读' not in page.locator('.defen_xtb').inner_text():
        return
    if page.locator('a.attachment-preview').count():
        read_attachment(page, task)
    button = page.locator('.btnCon button')
    if button.count() != 1 or '标记看完' not in button.inner_text():
        raise ValueError('未找到图文的“标记看完”按钮，需核对阅读器。')
    button.click()
    page.wait_for_function("() => !document.querySelector('.defen_xtb')?.innerText.includes('未阅读')", timeout=15000)


def pending_homework_detail(folder):
    path = folder / 'chapter_submission.json'
    if not path.exists():
        return ''
    summary = json.loads(path.read_text(encoding='utf-8-sig')).get('summary') or {}
    pending = summary.get('pending') or []
    if not pending:
        return ''
    return '；未提交题号（从1开始）：' + '、'.join(str(index + 1) for index in pending)


def verify_completed(page, task):
    guard(page, task['id'])
    page.reload(wait_until='domcontentloaded')
    tasks = directory(page)
    latest = next((t for t in tasks if t['id'] == task['id']), None)
    if latest is None:
        raise ValueError('任务已从目录中消失，已停止。')
    if latest['status'] != 'completed':
        raise ValueError('平台尚未确认当前任务完成，已保留断点。')
    return tasks


def execute_task(page, saved, statefile, task, deadline, kinds=None):
    """Run one item; returns 'completed' or 'waiting' (AI request needs an answer)."""
    wait_for_manual_verification(page,deadline)
    nickname = own_nickname(page)
    if saved.get('account_nickname') and saved['account_nickname'] != nickname:
        raise ValueError(f'当前登录账号 {nickname} 与断点记录不一致，已停止。')
    saved['account_nickname'] = nickname
    history = saved['history'].setdefault(str(task['id']), {})
    item = page.locator(f'#unit-item-{task["id"]}')
    item.wait_for(state='attached', timeout=20000)
    if item.count() != 1:
        raise ValueError('目录中找不到当前任务，已停止。')
    # An uncertain external publication must survive all resume paths, including
    # missing or stale AI responses; only verified platform evidence clears it.
    uncertain_send = history.get('status') == 'sending'
    history.update({'name': task['name'], 'kind': task['kind'],
                    'status': 'sending' if uncertain_send else 'running', 'started_at': now()})
    saved['current'] = task
    saved['updated_at'] = now()
    write_json(statefile, saved)
    if not urlparse(page.url).path.endswith('/'+str(task['id'])):
        item.evaluate('el => el.click()')
        try:
            page.wait_for_function('id => location.pathname.endsWith("/" + id)', arg=task['id'], timeout=15000)
        except PlaywrightError as exc:
            raise ValueError('无法打开当前任务，可能被锁定或目录已变化。') from exc
    wait_for_manual_verification(page,deadline)
    folder = None
    if task['kind'] in ('discussion', 'homework'):
        request = prepare_ai(page, task)
        folder = REPORTS / 'workflow_ai' / str(task['id'])
        write_json(folder / 'request.json', request)
        response_file = folder / 'response.json'
        if not response_file.exists():
            if not uncertain_send:
                history['status'] = 'waiting_ai'
            saved['updated_at'] = now()
            write_json(statefile, saved)
            print(f'等待 DSH：{folder / "request.json"}', flush=True)
            return 'waiting'
        response = json.loads(response_file.read_text(encoding='utf-8-sig'))
        if response.get('request_id') != request['request_id']:
            if not uncertain_send:
                history['status'] = 'waiting_ai'
            history['failure_reason'] = 'AI 结果指纹与当前请求不一致'
            saved['updated_at'] = now()
            write_json(statefile, saved)
            raise ValueError('AI 结果已过期，请按最新请求重新生成 response.json。')
        if task['kind'] == 'discussion':
            reply = checked_reply(request, response)
            evidence = publish_discussion(page, task, reply, saved, statefile)
            if evidence.get('nickname') and evidence['nickname'] != nickname:
                raise ValueError('新回复的昵称与当前账号不一致，请核对。')
            print(f"讨论已发布并在列表核验：{evidence.get('published_at')}", flush=True)
        else:
            write_json(folder / 'chapter_request.json', {
                'path': request['path'],
                'items': [{'index': i['index'], 'problem_id': i['problem_id'],
                           'request': i['request'], 'unsupported': i['unsupported']}
                          for i in request['items']]})
            write_json(folder / 'chapter_response.json', {
                'path': request['path'], 'answers': response.get('answers', [])})
            command = [sys.executable, str(Path(__file__).with_name('chapter_submit.py')),
                       '--reports', str(folder)]
            reviewed = [a['index'] for a in response.get('answers', [])
                        if a.get('reviewed') is True and str(a.get('review_basis') or '').strip()]
            for index in reviewed:
                command += ['--reviewed-index', str(index)]
            try:
                finished = subprocess.run(command, capture_output=True, text=True,
                                          timeout=max(60, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ValueError('章节提交超时，结果未知；请仅核验平台状态，不要重试。')
            sys.stdout.write(finished.stdout)
            sys.stderr.write(finished.stderr)
            if finished.returncode != 0:
                raise ValueError('章节提交中断：' + (finished.stderr.strip().splitlines() or ['退出码 %d' % finished.returncode])[-1])
    elif task['kind'] == 'video':
        handle_video(page, task, deadline)
    elif task['kind'] == 'article':
        handle_article(page, task)
    else:
        raise ValueError('未知任务类型，已停止。')
    try:
        tasks = verify_completed(page, task)
    except ValueError as exc:
        if task['kind'] == 'homework' and folder is not None:
            detail = pending_homework_detail(folder)
            if detail:
                raise ValueError(str(exc) + detail) from exc
        raise
    history.update({'status': 'completed', 'completed_at': now()})
    history.pop('failure_reason', None)
    saved['tasks'] = tasks
    saved['current'] = next_task(tasks, kinds)
    saved['updated_at'] = now()
    write_json(statefile, saved)
    return 'completed'


def record_failure(saved, task, exc):
    """Persist why the run stopped; an unknown publication stays 'sending'."""
    history = saved['history'].setdefault(str(task['id']), {})
    reason = str(exc).strip() or exc.__class__.__name__
    if history.get('status') != 'sending':
        history['status'] = 'failed'
    history['failure_reason'] = reason
    history['failed_at'] = now()
    history['name'] = task.get('name')
    saved['current'] = task
    saved['last_failure'] = {'leaf_id': task['id'], 'name': task.get('name'), 'reason': reason,
                             'at': history['failed_at']}
    saved['updated_at'] = now()
    write_json(STATE_FILE, saved)


def run(page, execute, max_seconds, kinds=None):
    saved = json.loads(STATE_FILE.read_text(encoding='utf-8')) if STATE_FILE.exists() else {'history': {}}
    course = saved.get('course') or '/'.join(urlparse(page.url).path.split('/')[:-2])
    saved['course'] = course
    path=urlparse(page.url).path
    if path!=course and not path.startswith(course+'/'):
        raise ValueError('当前课程与断点不匹配，已停止。')
    tasks = directory(page)
    task = next_task(tasks, kinds)
    saved.update({'tasks': tasks, 'current': task, 'updated_at': now()})
    write_json(STATE_FILE, saved)
    print(f"目录共 {len(tasks)} 项，已完成 {sum(t['status'] == 'completed' for t in tasks)} 项。", flush=True)
    if not execute:
        print('下一任务：' + (task['name'] if task else '全部完成'))
        return
    if task is None:
        print('平台目录中的任务均已完成。')
        return
    deadline = time.monotonic() + max_seconds
    saved['run'] = {'started_at': now(), 'max_seconds': max_seconds, 'result': 'running'}
    write_json(STATE_FILE, saved)
    while task:
        if time.monotonic() >= deadline:
            raise ValueError('本次运行时间到，断点已保存。')
        if task['status'] == 'unknown' or task['kind'] == 'unknown':
            raise ValueError('任务状态或类型未知，已暂停。')
        print(f"处理 {task['id']}：{task['name']}（{KIND_LABELS.get(task['kind'], task['kind'])}）", flush=True)
        try:
            result = execute_task(page, saved, STATE_FILE, task, deadline, kinds)
        except BaseException as exc:
            record_failure(saved, task, exc)
            raise
        if result == 'waiting':
            saved['run'].update({'result': 'waiting_ai', 'finished_at': now()})
            write_json(STATE_FILE, saved)
            return
        task = next_task(saved['tasks'], kinds)
    saved['run'].update({'result': 'all_completed', 'finished_at': now()})
    write_json(STATE_FILE, saved)
    print('平台目录中的任务均已完成。')


def status():
    if not STATE_FILE.exists():
        print('尚无断点，请先运行 scan。')
        return
    saved = json.loads(STATE_FILE.read_text(encoding='utf-8'))
    tasks = saved.get('tasks', [])
    counts = Counter(t['status'] for t in tasks)
    print(f"课程：{saved.get('course')}")
    print(f"断点更新：{saved.get('updated_at')}")
    print(f"共 {len(tasks)} 项：已完成 {counts['completed']}，未完成 {counts['incomplete']}，未知 {counts['unknown']}")
    for kind in ('video', 'article', 'discussion', 'homework'):
        subset = [t for t in tasks if t['kind'] == kind]
        if subset:
            done = sum(t['status'] == 'completed' for t in subset)
            print(f"  {KIND_LABELS[kind]}：{done}/{len(subset)} 已完成")
    current = saved.get('current')
    print('当前/下一任务：' + (f"{current['name']}（{KIND_LABELS.get(current['kind'], current['kind'])}，{current['status']}）" if current else '无'))
    history = saved.get('history') or {}
    waiting = [k for k, v in history.items() if v.get('status') == 'waiting_ai']
    failed = [k for k, v in history.items() if v.get('status') == 'failed']
    sending = [k for k, v in history.items() if v.get('status') == 'sending']
    print('等待 AI：' + ('、'.join(waiting) if waiting else '无'))
    print('失败：' + ('、'.join(failed) if failed else '无'))
    print('发送结果不明：' + ('、'.join(sending) if sending else '无'))
    failure = saved.get('last_failure')
    if failure:
        print(f"最近失败：{failure.get('name')}（{failure.get('leaf_id')}）{failure.get('reason')} @ {failure.get('at')}")
        print('恢复建议：核对原因后重新运行 run；确认页面未产生重复内容再继续。')
    print('下一步：运行 run，或处理 reports/workflow_ai 下缺少 response.json 的请求。')


def main():
    parser = argparse.ArgumentParser(description='按目录顺序处理未完成内容，支持断点恢复')
    parser.add_argument('action', choices=('scan', 'run', 'status'))
    parser.add_argument('--max-seconds', type=int, default=None, help='运行秒数；省略时弹窗选择分钟数')
    parser.add_argument('--kind', default='', help='只处理这些类型，逗号分隔：video,article,discussion,homework')
    args = parser.parse_args()
    if args.action == 'status':
        status()
        return
    if args.action == 'run':
        if args.max_seconds is None:
            args.max_seconds=choose_runtime_seconds()
            if args.max_seconds is None:
                print('已取消，未启动工作流。')
                return
        if args.max_seconds<=0:
            parser.error('运行时间必须大于0。')
        print(f'本次运行上限：{args.max_seconds/60:g} 分钟。',flush=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9223')
        pages = [q for c in browser.contexts for q in c.pages
                 if urlparse(q.url).hostname == 'www.xuetangx.com' and '/learn/space/' in q.url]
        if len(pages) != 1:
            raise ValueError('请打开唯一的新版课程标签页（网址含 /learn/space/）。')
        kinds = {k.strip() for k in args.kind.split(',') if k.strip()} or None
        run(pages[0], args.action == 'run', args.max_seconds or 0, kinds)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, PlaywrightError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
