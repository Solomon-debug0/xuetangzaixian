import sys
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dsh_question import make_request
from inspect_course import inspect_page
from fill_answer import fill_current_answer


class FillAnswerTests(unittest.TestCase):
    def test_multiple_choice_reconciles_selected_options(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.set_content('''<div class="question"><p class="title">多选题</p>
                <div class="leftQuestion"><div class="fuwenben">选择偶数</div>
                <p class="leftradio"><span class="radio_xtb">A</span><span>2</span></p>
                <p class="leftradio"><span class="radio_xtb">B</span><span>3</span></p>
                <p class="leftradio"><span class="radio_xtb">C</span><span>4</span></p></div></div>
                <div class="answerList"><span class="radio_xtb">A</span><span class="radio_xtb active">B</span><span class="radio_xtb">C</span></div>
                <script>window.clicks=0;document.querySelectorAll('.answerList span').forEach(el=>el.onclick=()=>{
                    window.clicks++;el.classList.toggle('active');});</script>''')
                request = make_request(inspect_page(page))
                response = {'question_id':request['question_id'],'answer':['A','C'],
                            'explanation':'2和4是偶数。','needs_review':False}
                self.assertEqual(fill_current_answer(page,request,response), ['A','C'])
                self.assertEqual(fill_current_answer(page,request,response), ['A','C'])
                self.assertEqual(page.evaluate('window.clicks'),3)
            finally:
                browser.close()

    def test_fill_idempotence_review_and_stale_question(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.set_content('''<div class="question"><p class="title">单选题</p>
                <div class="leftQuestion"><div class="fuwenben">2+2等于多少？</div>
                <p class="leftradio"><span class="radio_xtb">A</span><span>3</span></p>
                <p class="leftradio"><span class="radio_xtb">B</span><span>4</span></p></div></div>
                <div class="answerList"><span class="radio_xtb">A</span><span class="radio_xtb">B</span></div>
                <button onclick="window.submits++">提交</button>
                <script>window.clicks=0;window.submits=0;
                document.querySelectorAll('.answerList span').forEach(el=>el.onclick=()=>{
                    window.clicks++;document.querySelectorAll('.answerList span').forEach(x=>x.classList.remove('active'));
                    el.classList.add('active');});</script>''')
                request = make_request(inspect_page(page))
                response = {'question_id':request['question_id'],'answer':['B'],'explanation':'2+2=4','needs_review':True}
                with self.assertRaisesRegex(ValueError, '复核'):
                    fill_current_answer(page, request, response)
                self.assertEqual(page.evaluate('window.clicks'), 0)
                self.assertEqual(fill_current_answer(page, request, response, reviewed=True), ['B'])
                self.assertEqual(fill_current_answer(page, request, response, reviewed=True), ['B'])
                self.assertEqual(page.evaluate('window.clicks'), 1)
                self.assertEqual(page.evaluate('window.submits'), 0)
                page.locator('.fuwenben').evaluate("el => el.textContent='新题目'")
                with self.assertRaisesRegex(ValueError, '变化'):
                    fill_current_answer(page, request, response, reviewed=True)
                self.assertEqual(page.evaluate('window.clicks'), 1)
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
