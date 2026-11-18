import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow as workflow_module
from workflow import next_task, request_digest, checked_reply, record_failure


class WorkflowTests(unittest.TestCase):
    def test_directory_order_and_unknown_are_preserved(self):
        tasks=[{'id':3,'status':'completed'},{'id':20,'status':'incomplete'},
               {'id':1,'status':'incomplete'}]
        self.assertEqual(next_task(tasks)['id'],20)
        tasks[1]['status']='unknown'
        self.assertEqual(next_task(tasks)['status'],'unknown')
        self.assertIsNone(next_task([tasks[0]]))

    def test_reply_must_match_topic_and_not_be_empty(self):
        request={'kind':'discussion','leaf_id':123,'topic':'讨论大数定律'}
        request['request_id']=request_digest(request)
        response={'request_id':request['request_id'],'kind':'discussion','reply':'大数定律刻画样本均值的收敛。'}
        self.assertEqual(checked_reply(request,response),response['reply'])
        for bad in ({**response,'request_id':'old'},{**response,'reply':''},{**response,'kind':'homework'}):
            with self.assertRaises(ValueError):checked_reply(request,bad)

    def test_digest_survives_submission_snapshot_changes(self):
        request={'kind':'homework','leaf_id':10,'path':'/p/10',
                 'items':[{'index':0,'problem_id':1,'request':{'question_id':'q0'}}],
                 'state_snapshot':[{'index':0,'problem_id':1,'submitted':False}]}
        digest=request_digest(request)
        later=json.loads(json.dumps(request))
        later['state_snapshot'][0]['submitted']=True
        later['request_id']='stale'
        self.assertEqual(request_digest(later),digest)
        later['items'][0]['request']['question_id']='q1'
        self.assertNotEqual(request_digest(later),digest)

    def test_failure_is_persisted_and_unknown_send_stays_sending(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'state.json'
            original=workflow_module.STATE_FILE
            workflow_module.STATE_FILE=path
            try:
                saved={'course':'c','history':{'5':{'status':'sending'}}}
                record_failure(saved,{'id':5,'name':'讨论1-2'},ValueError('已点击但未见回复'))
                entry=json.loads(path.read_text(encoding='utf-8'))['history']['5']
                self.assertEqual(entry['status'],'sending')
                self.assertEqual(entry['failure_reason'],'已点击但未见回复')
                stored=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(stored['last_failure']['leaf_id'],5)
                record_failure({'history':{}},{'id':6,'name':'视频'},ValueError('播放失败'))
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['history']['6']['status'],'failed')
            finally:
                workflow_module.STATE_FILE=original


if __name__=='__main__':unittest.main()
