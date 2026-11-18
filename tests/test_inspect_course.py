import sys
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from inspect_course import inspect_page, pending_tasks


class InspectTests(unittest.TestCase):
    def test_partial_video_progress_is_unfinished(self):
        with sync_playwright() as p:
            b=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=b.new_page()
                page.set_content('<div class="course-action-lesson-left"></div><div id="unit-item-1"><div class="item-status"><div class="status-pie"></div></div></div>')
                page.evaluate("""() => document.querySelector('.course-action-lesson-left').__vue__={$data:{listName:[{id:1,name:'视频',leaf_type:0}],schedules:{1:0.0015}}}""")
                self.assertEqual(inspect_page(page)['tasks'][0]['status'],'incomplete')
                page.evaluate("document.querySelector('.course-action-lesson-left').__vue__.$data.schedules={}")
                self.assertEqual(inspect_page(page)['tasks'][0]['status'],'unknown')
            finally:b.close()

    def test_tasks_status_and_question(self):
        with sync_playwright() as p:
            b = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = b.new_page()
                page.set_content('''<div class="course-action-lesson-left"></div>
                  <div id="unit-item-1"><div class="item-status"><i class="is-finish"></i></div></div>
                  <div id="unit-item-2"><div class="item-status"></div></div>
                  <div class="question"><p class="title">单选题 (1分)</p>
                  <div class="leftQuestion"><div class="fuwenben">例题：选择正确选项<img src="data:image/png;base64,AA"></div>
                  <p class="leftradio"><span class="radio_xtb">A</span><span>选项一</span></p>
                  <p class="leftradio"><span class="radio_xtb">B</span><span>选项二</span></p></div></div>''')
                page.evaluate('''() => {
                  document.querySelector('.course-action-lesson-left').__vue__ = {$data:{listName:[
                    {id:1,name:'视频',leaf_type:0}, {id:2,name:'作业',leaf_type:6},
                    {id:3,name:'未知状态图文',leaf_type:3}, {id:4,name:'新类型',leaf_type:99}
                  ]}};
                }''')
                result = inspect_page(page)
                self.assertEqual([t['status'] for t in result['tasks']], ['completed','incomplete','unknown','unknown'])
                self.assertEqual(result['tasks'][1]['kind'], 'homework')
                self.assertEqual([t['id'] for t in pending_tasks(result['tasks'])], [2])
                question = result['question']
                self.assertEqual(question['type'], 'single_choice')
                self.assertEqual(question['options'], [{'label':'A','text':'选项一'}, {'label':'B','text':'选项二'}])
                self.assertTrue(question['has_images'])
                page.set_content('<div>没有题目</div>')
                empty = inspect_page(page)
                self.assertIsNone(empty['question'])
                self.assertEqual(empty['tasks'], [])
            finally:
                b.close()


if __name__ == '__main__':
    unittest.main()
