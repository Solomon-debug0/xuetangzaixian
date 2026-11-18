"""Read the open course directory and current question without clicking or submitting."""
import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from homework_dom import HOMEWORK_QUESTION


def inspect_page(page):
    return page.evaluate(r'''arg => {
        const clean = e => (e?.textContent || '').replace(/\s+/g, ' ').trim();
        const data = document.querySelector('.course-action-lesson-left')?.__vue__?.$data;
        const kinds = {0:'video',3:'article',4:'discussion',6:'homework'};
        const tasks = (Array.isArray(data?.listName) ? data.listName : []).map(item => {
            const statusNode = document.getElementById('unit-item-' + item.id)?.querySelector('.item-status');
            // A missing status container is unknown, never presumed unfinished.
            const progress = data?.schedules?.[item.id];
            const partial = !!statusNode?.querySelector('.status-pie') &&
                typeof progress === 'number' && Number.isFinite(progress) && progress >= 0 && progress < 1;
            const status = !statusNode ? 'unknown' : statusNode.querySelector('.is-finish') ? 'completed' :
                (statusNode.children.length === 0 || partial ? 'incomplete' : 'unknown');
            return {id:item.id,name:item.name,leaf_type:item.leaf_type,
                kind:kinds[item.leaf_type] || 'unknown',status};
        });
        const root = document.querySelector(arg.homeworkQuestion) || document.querySelector('.question');
        let question = null;
        if (root) {
            const stem = root.querySelector('.leftQuestion .fuwenben, .leftQuestion .fuweben');
            const title = clean(root.querySelector('.title'));
            const text = clean(stem);
            let options = [...root.querySelectorAll('.leftradio')].map(row => {
                const label = clean(row.querySelector('.radio_xtb'));
                const clone = row.cloneNode(true);
                clone.querySelector('.radio_xtb')?.remove();
                return {label,text:clean(clone)};
            });
            const isJudge = title.includes('判断');
            if (isJudge && options.length === 0) {
                // 判断题没有文字选项，作答区是两个“对/错”按钮。
                const spans = [...document.querySelectorAll('.answerCon .answerList .radio_xtb.panduan')];
                options = spans.length === 2
                    ? [{label:'true',text:'正确'},{label:'false',text:'错误'}]
                    : options;
            }
            const questionType = title.includes('单选') ? 'single_choice' : title.includes('多选') ? 'multiple_choice' :
                 isJudge ? 'judge' : title.includes('填空') ? 'fill' : 'unknown';
            if (text || stem?.querySelector('img')) question = {
                type:questionType,
                title,text,options,has_images:!!root.querySelector('img'),
                has_math:!!root.querySelector('math,.katex,.MathJax,script[type^="math/tex"]')
            };
        }
        return {path:location.pathname,directory_found:Array.isArray(data?.listName),tasks,question};
    }''', {'homeworkQuestion': HOMEWORK_QUESTION})


def pending_tasks(tasks):
    """Only positively identified unfinished tasks belong in the pending list."""
    return [t for t in tasks if t['status'] == 'incomplete' and t['kind'] != 'unknown']


def main():
    parser = argparse.ArgumentParser(description='只读检查课程目录和当前题目')
    parser.add_argument('--port', type=int, default=9223)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'reports')
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f'http://127.0.0.1:{args.port}')
        pages = [page for context in browser.contexts for page in context.pages
                 if urlparse(page.url).hostname == 'www.xuetangx.com'
                 and urlparse(page.url).path.startswith('/learn/')]
        if len(pages) != 1:
            raise SystemExit(f'找到 {len(pages)} 个课程标签页，请只保留一个目标课程页后重试。')
        page = pages[0]
        page.wait_for_selector('.course-action-lesson-left', state='attached', timeout=15000)
        page.wait_for_function("Array.isArray(document.querySelector('.course-action-lesson-left')?.__vue__?.$data?.listName)", timeout=15000)
        result = inspect_page(page)
    result['pending_tasks'] = pending_tasks(result['tasks'])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'course_inspection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    kinds = {'video':'视频','article':'图文','discussion':'讨论','homework':'作业','unknown':'未知类型'}
    states = {'completed':'已完成','incomplete':'未完成','unknown':'未知'}
    lines = ['# 课程只读检查', '', '仅检查当前页面，未选择答案、提交作业或修改课程进度。', '',
             '完成状态来自页面目录标记，不代表作业满分或视频实际观看时长。', '']
    for kind, label in kinds.items():
        subset = [t for t in result['tasks'] if t['kind'] == kind]
        if subset:
            counts = Counter(t['status'] for t in subset)
            line = f"{label}：共 {len(subset)}，已完成 {counts['completed']}，未完成 {counts['incomplete']}，未知 {counts['unknown']}"
            lines.append(line + '\n')
            print(line)
    lines += ['## 任务列表', '', '| 类型 | 名称 | 状态 |', '| --- | --- | --- |']
    for task in result['tasks']:
        name = str(task['name']).replace('|', '\\|').replace('\n',' ')
        lines.append(f"| {kinds[task['kind']]} | {name} | {states[task['status']]} |")
    question = result['question']
    lines += ['', '## 当前题目', '']
    if question:
        lines += [question['title'], '', question['text'], '']
        lines += [f"- {option['label']}：{option['text']}" for option in question['options']]
        if question['has_images'] or question['has_math']:
            lines += ['', '题目含图片或公式，纯文本导出可能不完整，需要核对原页面。']
        print(f"已读取当前题目：{question['type']}，{len(question['options'])} 个选项")
    else:
        lines += ['当前页面未识别到题目。请手动打开一道作业题后再次运行。']
        print('当前页面未识别到题目。')
    (args.output / '课程检查报告.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'报告已保存：{args.output}')


if __name__ == '__main__':
    main()
