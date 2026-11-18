import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chapter_submit import first_question, state, submit_once
from dsh_question import make_request
from fill_answer import fill_current_answer
from inspect_course import inspect_page
from workflow import homework_items


ROOT_CLASSES = {
    'old': 'courseActionExamine',
    'new': 'courseActionExamineLearnSpace',
}


def homework_markup(root_class, stem_class='fuwenben'):
    return f'''<div class="{root_class}" id="homework">
      <div class="content">
        <div class="tabbar">
          <i class="iconfont unselectable unselect">prev</i>
          <span class="curent">1</span><span class="total">/1</span>
          <i class="iconfont right unselectable">next</i>
        </div>
        <div class="question">
          <p class="title">单选题 (2分)</p>
          <div class="leftQuestion">
            <div class="{stem_class}">2+2等于多少？</div>
            <p class="leftradio"><span class="radio_xtb">A</span><span>3</span></p>
            <p class="leftradio"><span class="radio_xtb">B</span><span>4</span></p>
          </div>
        </div>
        <div class="answer">
          <div class="answerList"><span class="radio_xtb">A</span><span class="radio_xtb">B</span></div>
          <div class="btnCon"><button class="btn">提交(剩余1次)</button></div>
        </div>
      </div>
    </div>'''


def attach_homework(page, *, apply_answer_sheet=False, be_in_force=False):
    page.evaluate('''arg => {
        const d = {
            active: 0,
            submitType: 2,
            ifneedSubmit: false,
            ifCanChangeActive: true,
            is_apply_answer_sheet: arg.apply,
            be_in_force: arg.force,
            prictice: [{
                problem_id: 1,
                type: 1,
                user: {my_count: 0},
                content: {
                    Body: '<p>2+2等于多少？</p>',
                    Options: [{key: 'A', value: '3'}, {key: 'B', value: '4'}]
                }
            }]
        };
        document.querySelector('#homework').__vue__ = {$data: d};
        window.clicks = 0;
        window.answerClicks = 0;
        document.querySelectorAll('.answerList .radio_xtb').forEach(el => {
            el.addEventListener('click', () => {
                window.answerClicks += 1;
                el.classList.toggle('active');
            });
        });
        document.querySelector('.btnCon button').addEventListener('click', () => {
            window.clicks += 1;
            d.prictice[0].user.my_count += 1;
        });
    }''', {'apply': apply_answer_sheet, 'force': be_in_force})


def answer_for(request):
    return {'question_id': request['question_id'], 'answer': ['B'],
            'explanation': '2+2=4。', 'needs_review': False}


class HomeworkVersionTests(unittest.TestCase):
    def test_both_versions_read_fill_and_submit_once(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                for version, root_class in ROOT_CLASSES.items():
                    with self.subTest(version=version):
                        page = browser.new_page()
                        try:
                            page.set_content(homework_markup(root_class))
                            attach_homework(page)
                            inspection = inspect_page(page)
                            self.assertEqual(inspection['question']['text'], '2+2等于多少？')
                            self.assertEqual(inspection['question']['options'],
                                             [{'label': 'A', 'text': '3'}, {'label': 'B', 'text': '4'}])
                            request = make_request(inspection)
                            current = state(page)
                            self.assertIsNotNone(current)
                            self.assertEqual(current['active'], 0)
                            items = homework_items(page)
                            self.assertEqual(items[0]['question']['text'], '2+2等于多少？')
                            self.assertFalse(items[0]['submitted'])
                            self.assertEqual(fill_current_answer(page, request, answer_for(request)), ['B'])
                            self.assertEqual(page.evaluate('window.answerClicks'), 1)
                            submit_once(page, 0, 1)
                            self.assertEqual(page.evaluate('window.clicks'), 1)
                            with self.assertRaises(ValueError):
                                submit_once(page, 0, 1)
                            self.assertEqual(page.evaluate('window.clicks'), 1)
                            self.assertTrue(homework_items(page)[0]['submitted'])
                        finally:
                            page.close()
            finally:
                browser.close()

    def test_new_version_editable_flag_blocks_fill(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                try:
                    page.set_content(homework_markup(ROOT_CLASSES['new']))
                    attach_homework(page, apply_answer_sheet=True)
                    request = make_request(inspect_page(page))
                    with self.assertRaisesRegex(ValueError, '不可编辑'):
                        fill_current_answer(page, request, answer_for(request))
                    self.assertEqual(page.evaluate('window.answerClicks'), 0)
                finally:
                    page.close()
            finally:
                browser.close()

    def test_new_version_switches_to_first_question(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                try:
                    page.set_content('''<div class="courseActionExamineLearnSpace">
                      <div class="tabbar">
                        <i class="unselect" onclick="if(d.ifCanChangeActive){d.active--;d.ifCanChangeActive=false;setTimeout(()=>d.ifCanChangeActive=true,100);}">prev</i>
                        <i class="right">next</i>
                      </div></div>
                      <script>const d={active:2,prictice:[{problem_id:1,user:{my_count:0}},{problem_id:2,user:{my_count:0}},{problem_id:3,user:{my_count:0}}],ifCanChangeActive:true};document.querySelector('.courseActionExamineLearnSpace').__vue__={$data:d};</script>''')
                    first_question(page)
                    self.assertEqual(page.evaluate('d.active'), 0)
                finally:
                    page.close()
            finally:
                browser.close()

    def test_new_version_readonly_extraction_prefers_homework_shell(self):
        decoy = '''<div class="question"><p class="title">单选题</p>
          <div class="leftQuestion"><div class="fuwenben">外部干扰题</div>
            <p class="leftradio"><span class="radio_xtb">A</span><span>干扰一</span></p>
            <p class="leftradio"><span class="radio_xtb">B</span><span>干扰二</span></p>
          </div></div>'''
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                for stem_class in ('fuwenben', 'fuweben'):
                    with self.subTest(stem_class=stem_class):
                        page = browser.new_page()
                        try:
                            page.set_content(decoy + homework_markup(ROOT_CLASSES['new'], stem_class))
                            question = inspect_page(page)['question']
                            self.assertEqual(question['text'], '2+2等于多少？')
                            self.assertEqual(question['options'],
                                             [{'label': 'A', 'text': '3'}, {'label': 'B', 'text': '4'}])
                        finally:
                            page.close()
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
