import json
import sys
import tempfile
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chapter_submit import submit_once, first_question, summary_of, save_snapshot


class SubmitTests(unittest.TestCase):
    def test_resume_visits_earlier_unanswered_questions(self):
        with sync_playwright() as p:
            b=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=b.new_page()
                page.set_content('''<div class="courseActionExamine"><div class="tabbar"><i onclick="if(d.ifCanChangeActive){d.active--;d.ifCanChangeActive=false;setTimeout(()=>d.ifCanChangeActive=true,100);}">prev</i><i class="right">next</i></div></div>
                <script>const d={active:2,prictice:[],ifCanChangeActive:true};document.querySelector('.courseActionExamine').__vue__={$data:d};</script>''')
                first_question(page)
                self.assertEqual(page.evaluate('d.active'),0)
            finally:b.close()

    def test_submit_confirmed_once_and_never_retry_submitted_question(self):
        with sync_playwright() as p:
            b = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = b.new_page()
                page.set_content('''<div class="courseActionExamine"><div class="btnCon"><button>提交(剩余1次)</button></div></div>
                <script>window.clicks=0;const d={active:0,prictice:[{problem_id:1,user:{my_count:0}}]};
                document.querySelector('.courseActionExamine').__vue__={$data:d};
                document.querySelector('button').onclick=()=>{window.clicks++;d.prictice[0].user.my_count++;};</script>''')
                submit_once(page,0,1)
                self.assertEqual(page.evaluate('window.clicks'),1)
                with self.assertRaises(ValueError): submit_once(page,0,1)
                self.assertEqual(page.evaluate('window.clicks'),1)
            finally: b.close()

    def test_summary_lists_pending_and_unsupported(self):
        log=[{'index':0,'status':'already_submitted'},{'index':1,'status':'submitted','answer':['A']},
             {'index':2,'status':'unsupported','reason':'题目含图片'},{'index':3,'status':'skipped_review_or_missing_answer'}]
        summary=summary_of(log,4)
        self.assertEqual(summary['pending'],[2,3])
        self.assertEqual(summary['unsupported'],1)
        self.assertEqual(summary['already_submitted'],1)
        self.assertFalse(summary['stopped'])

    def test_snapshot_writes_run_file_and_appends_log(self):
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name)
            document={'path':'/p','run_id':'R1','started_at':'t','finished_at':'t',
                      'summary':summary_of([],1),'items':[]}
            save_snapshot(directory,document,False)
            self.assertFalse((directory/'chapter_submission_log.jsonl').exists())
            save_snapshot(directory,document,True)
            stored=json.loads((directory/'chapter_submission.json').read_text(encoding='utf-8'))
            self.assertEqual(stored['run_id'],'R1')
            self.assertTrue((directory/'chapter_submission_R1.json').exists())
            lines=(directory/'chapter_submission_log.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines),1)
            self.assertEqual(json.loads(lines[0])['run_id'],'R1')


if __name__ == '__main__': unittest.main()
