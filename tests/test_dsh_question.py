import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dsh_question import make_request, validate_response


class DshQuestionTests(unittest.TestCase):
    def setUp(self):
        self.question = {'type':'single_choice','text':'2+2等于多少？',
                         'options':[{'label':'A','text':'3'},{'label':'B','text':'4'}],
                         'has_images':False,'has_math':False}
        self.request = make_request({'path':'/example','question':self.question})

    def test_validate_and_reject_invalid_or_stale_answers(self):
        answer = {'question_id':self.request['question_id'],'answer':['B'],
                  'explanation':'2加2等于4。','needs_review':False}
        self.assertEqual(validate_response(self.request, answer)['answer'], ['B'])
        for bad in ({**answer,'question_id':'stale'}, {**answer,'answer':['Z']},
                    {**answer,'answer':['A','B']}, {**answer,'needs_review':'false'},
                    {**answer,'explanation':''}):
            with self.assertRaises(ValueError):
                validate_response(self.request, bad)

    def test_question_changes_change_id_and_incomplete_questions_stop(self):
        changed = make_request({'question':{**self.question,'text':'3+3等于多少？'}})
        self.assertNotEqual(self.request['question_id'],changed['question_id'])
        for update in ({'has_images':True},{'has_math':True},{'type':'unknown'},
                       {'text':''},{'options':[]}):
            with self.assertRaises(ValueError):
                make_request({'question':{**self.question,**update}})


if __name__ == '__main__':
    unittest.main()
