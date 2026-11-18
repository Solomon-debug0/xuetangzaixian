"""Fill one verified answer through visible controls; never submit."""
import argparse
import json
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Error as PlaywrightError

from dsh_question import REPORTS, make_request, validate_response
from homework_dom import HOMEWORK_ROOT
from inspect_course import inspect_page


def fill_current_answer(page, request, response, reviewed=False):
    response = validate_response(request, response)
    if make_request(inspect_page(page)) != request:
        raise ValueError('网页题目已变化，请重新读取并生成答案。')
    if response['needs_review'] and not reviewed:
        raise ValueError('该答案需要复核；请先阅读解析，确认后使用 --reviewed。未填写。')
    editable = page.evaluate('''root => {
        const v=document.querySelector(root)?.__vue__;
        if (!v) return null;
        const d=v.$data, q=d.prictice?.[d.active];
        return !!q && !d.is_apply_answer_sheet && !d.be_in_force &&
            (q.user?.my_count === 0 || !!q.if_edit);
    }''', HOMEWORK_ROOT)
    if editable is False:
        raise ValueError('当前题目不可编辑，可能已经提交或被锁定。未填写。')
    is_judge = request['question']['type'] == 'judge'
    controls = page.locator('.answerList .radio_xtb.panduan' if is_judge else '.answerList .radio_xtb')
    expected = [o['label'] for o in request['question']['options']]
    if is_judge:
        if controls.count() != 2:
            raise ValueError('判断题作答控件数量异常，未填写。')
        actual = ['true', 'false']
    else:
        actual = [controls.nth(i).inner_text().strip() for i in range(controls.count())]
    if actual != expected:
        raise ValueError('作答区选项与题目不一致，未填写。')
    for i in range(controls.count()):
        if not controls.nth(i).is_visible() or not controls.nth(i).is_enabled():
            raise ValueError('作答控件不可用，未填写。')
    desired = set(response['answer'])
    multiple = request['question']['type'] == 'multiple_choice'
    for index, label in enumerate(actual):
        # Recheck immediately before each click; never act on a stale question.
        if make_request(inspect_page(page)) != request:
            raise ValueError('填写时题目发生变化，已停止。')
        control = controls.nth(index)
        selected = 'active' in (control.get_attribute('class') or '').split()
        if (multiple and selected != (label in desired)) or (not multiple and label in desired and not selected):
            control.click(timeout=5000)
    selected = [expected[i] if is_judge else controls.nth(i).inner_text().strip()
                for i in range(controls.count())
                if 'active' in (controls.nth(i).get_attribute('class') or '').split()]
    if set(selected) != desired:
        raise ValueError('点击后选中状态未得到确认，已停止。未提交。')
    return selected


def main():
    parser = argparse.ArgumentParser(description='填写 DSH 当前单题答案，不提交')
    parser.add_argument('--port', type=int, default=9223)
    parser.add_argument('--reviewed', action='store_true', help='你已阅读并确认需要复核的答案')
    args = parser.parse_args()
    request = json.loads((REPORTS / 'dsh_request.json').read_text(encoding='utf-8-sig'))
    response = json.loads((REPORTS / 'dsh_response.json').read_text(encoding='utf-8-sig'))
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f'http://127.0.0.1:{args.port}')
        pages = [page for context in browser.contexts for page in context.pages
                 if urlparse(page.url).hostname == 'www.xuetangx.com'
                 and urlparse(page.url).path.startswith('/learn/')]
        if len(pages) != 1:
            raise ValueError('请只保留一个目标课程标签页。')
        selected = fill_current_answer(pages[0], request, response, args.reviewed)
    print('当前题已选中：' + '、'.join(selected) + '。尚未提交，请在网页核对。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, PlaywrightError) as exc:
        raise SystemExit(str(exc))
