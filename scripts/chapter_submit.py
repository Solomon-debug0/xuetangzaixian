"""Submit the current chapter's validated DSH answers through visible controls.

Every run leaves an append-only record: the latest snapshot, one snapshot per
run id, and one line appended to chapter_submission_log.jsonl. A question the
reader could not parse stays pending instead of being guessed.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from dsh_question import REPORTS, validate_response
from fill_answer import fill_current_answer
from homework_dom import HOMEWORK_ROOT

DONE = ('submitted', 'already_submitted')


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def state(page):
    return page.evaluate('''root => {
        const d=document.querySelector(root)?.__vue__?.$data;
        return d ? {active:d.active,items:d.prictice.map(x=>({
            problem_id:x.problem_id,count:x.user?.my_count,score:x.user?.my_score,correct:x.user?.is_correct
        }))} : null;
    }''', HOMEWORK_ROOT)


def submit_once(page,index,problem_id):
    before=state(page)
    if (not before or before['active'] != index or
        before['items'][index]['problem_id'] != problem_id or
        before['items'][index]['count'] != 0):
        raise ValueError('题目或提交状态发生变化，未提交。')
    # submitType=2 still exposes one visible submit control for the current
    # question. The old page nests it in .btnCon; the learn-space page renders
    # an el-popover reference button directly, so match by visible label.
    found=[]
    buttons=page.locator(f'{HOMEWORK_ROOT} button')
    for i in range(buttons.count()):
        candidate=buttons.nth(i)
        try:
            if candidate.inner_text().strip().startswith('提交') and candidate.is_visible():
                found.append(candidate)
        except PlaywrightError:
            continue
    if len(found)!=1:
        raise ValueError('找不到唯一的提交按钮，未提交。')
    button=found[0]
    if not button.is_enabled() or 'disable' in (button.get_attribute('class') or ''):
        raise ValueError('提交按钮不可用。')
    button.click(timeout=5000)
    # No automatic retry: a timeout can mean the server accepted the answer.
    page.wait_for_function('''arg => {
        const d=document.querySelector(arg.root)?.__vue__?.$data;
        const q=d?.prictice?.[arg.index];
        return q?.problem_id === arg.id && q?.user?.my_count > 0;
    }''', arg={'index':index,'id':problem_id,'root':HOMEWORK_ROOT}, timeout=20000)


def first_question(page):
    current=state(page)
    while current['active']>0:
        target=current['active']-1
        wait_navigation(page)
        page.locator(f'{HOMEWORK_ROOT} .tabbar > i:not(.right)').click(timeout=5000)
        page.wait_for_function("arg => document.querySelector(arg.root).__vue__.$data.active === arg.target",
                               arg={'root':HOMEWORK_ROOT,'target':target}, timeout=10000)
        current=state(page)


def wait_navigation(page):
    page.wait_for_function("root => document.querySelector(root)?.__vue__?.$data?.ifCanChangeActive !== false",
                           arg=HOMEWORK_ROOT, timeout=10000)


def summary_of(log,total):
    """Counted outcome plus the indices that still lack a submitted answer."""
    counts={name:sum(1 for e in log if e['status']==name) for name in DONE}
    stopped=any(e['status']=='stopped' for e in log)
    done={e['index'] for e in log if e['status'] in DONE}
    return {'total':total,'submitted':counts['submitted'],'already_submitted':counts['already_submitted'],
            'skipped':sum(1 for e in log if e['status'].startswith('skipped')),
            'unsupported':sum(1 for e in log if e['status']=='unsupported'),
            'stopped':stopped,'pending':[i for i in range(total) if i not in done]}


def save_snapshot(directory,document,finished):
    """Write the latest snapshot, one file per run, and append the finished run to a log."""
    text=json.dumps(document,ensure_ascii=False,indent=2)
    (directory/'chapter_submission.json').write_text(text,encoding='utf-8')
    (directory/f"chapter_submission_{document['run_id']}.json").write_text(text,encoding='utf-8')
    if finished:
        with (directory/'chapter_submission_log.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(document,ensure_ascii=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description='提交当前章节已分析的答案，不重复提交')
    parser.add_argument('--reviewed-index',type=int,action='append',default=[])
    parser.add_argument('--reports',type=Path,default=REPORTS)
    args=parser.parse_args()
    directory=args.reports
    batch=json.loads((directory/'chapter_request.json').read_text(encoding='utf-8-sig'))
    response=json.loads((directory/'chapter_response.json').read_text(encoding='utf-8-sig'))
    if batch['path'] != response['path']:
        raise ValueError('章节不匹配。')
    items={item['index']:item for item in batch['items']}
    answers={}
    reviewed=set(args.reviewed_index)
    for answer in response['answers']:
        i=answer['index']
        if i in answers or i not in items:
            raise ValueError('答案题号重复或不匹配。')
        if items[i].get('request') is None:
            raise ValueError(f'第{i+1}题当前无法解析，不能提交答案。')
        answers[i]=validate_response(items[i]['request'],answer)
        if answer.get('reviewed') is True and str(answer.get('review_basis') or '').strip():
            reviewed.add(i)
    run_id=datetime.now().strftime('%Y%m%dT%H%M%S')
    started_at=now()
    log=[]

    def snapshot(finished=False):
        document={'path':batch['path'],'run_id':run_id,'started_at':started_at,
                  'finished_at':now() if finished else None,
                  'summary':summary_of(log,len(items)),'items':log}
        save_snapshot(directory,document,finished)

    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp('http://127.0.0.1:9223')
        pages=[q for c in browser.contexts for q in c.pages
               if urlparse(q.url).hostname=='www.xuetangx.com' and urlparse(q.url).path==batch['path']]
        if len(pages)!=1: raise ValueError('需要唯一的目标章节标签页。')
        page=pages[0]
        current=state(page)
        if not current or len(current['items'])!=len(items): raise ValueError('题目数量不匹配。')
        first_question(page)
        try:
            for i in range(len(items)):
                if urlparse(page.url).path!=batch['path']: raise ValueError('课程页面变化，停止。')
                current=state(page)
                if current['active']!=i: raise ValueError('题号变化，停止。')
                item=items[i]
                if current['items'][i]['problem_id']!=item['problem_id']: raise ValueError('题目标识变化。')
                if current['items'][i]['count']>0:
                    log.append({'index':i,'status':'already_submitted'})
                elif item.get('request') is None:
                    log.append({'index':i,'status':'unsupported','reason':item.get('unsupported')})
                elif i not in answers:
                    log.append({'index':i,'status':'skipped_review_or_missing_answer'})
                elif answers[i]['needs_review'] and i not in reviewed:
                    log.append({'index':i,'status':'skipped_review_or_missing_answer',
                                'reason':'答案被标记为需要人工核对，未放行'})
                else:
                    try:
                        fill_current_answer(page,item['request'],answers[i],reviewed=i in reviewed)
                        # Check the question again inside fill_current_answer immediately before selection.
                        submit_once(page,i,item['problem_id'])
                        log.append({'index':i,'answer':answers[i]['answer'],'status':'submitted',
                                    'platform':state(page)['items'][i]})
                        print(f"第{i+1}题已提交：{'、'.join(answers[i]['answer'])}",flush=True)
                    except Exception as exc:
                        log.append({'index':i,'status':'stopped','reason':str(exc)})
                        snapshot()
                        raise
                snapshot()
                if i+1<len(items):
                    wait_navigation(page)
                    page.locator(f'{HOMEWORK_ROOT} .tabbar > i.right').click(timeout=5000)
                    page.wait_for_function("arg => document.querySelector(arg.root).__vue__.$data.active === arg.index",
                                           arg={'root':HOMEWORK_ROOT,'index':i+1}, timeout=10000)
        finally:
            snapshot(finished=True)
    result=json.loads((directory/'chapter_submission.json').read_text(encoding='utf-8'))
    print('章节处理结束，详情：reports/chapter_submission.json' if directory==REPORTS
          else f"章节处理结束，详情：{directory/'chapter_submission.json'}")
    print('摘要：' + json.dumps(result['summary'],ensure_ascii=False))


if __name__=='__main__':
    try: main()
    except (ValueError,OSError,PlaywrightError) as exc: raise SystemExit(str(exc))
