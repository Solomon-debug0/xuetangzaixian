import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow


class ResumeGuardsTests(unittest.TestCase):
    def test_resume_waits_for_directory_item_to_render(self):
        task={'id':5,'name':'讨论','kind':'discussion','status':'incomplete'}
        saved={'history':{}}
        request={'kind':'discussion','request_id':'fingerprint','topic':'主题'}
        page=Mock()
        page.url='https://www.xuetangx.com/learn/space/course/video/5'
        item=page.locator.return_value
        item.count.return_value=0
        item.wait_for.side_effect=lambda **kwargs:setattr(item.count,'return_value',1)
        with tempfile.TemporaryDirectory() as root:
            reports=Path(root)
            with patch.object(workflow,'REPORTS',reports), \
                 patch.object(workflow,'wait_for_manual_verification'), \
                 patch.object(workflow,'own_nickname',return_value='test-account'), \
                 patch.object(workflow,'prepare_ai',return_value=request):
                self.assertEqual(workflow.execute_task(page,saved,reports/'state.json',task,time.monotonic()+30),'waiting')
                item.wait_for.assert_called_once_with(state='attached',timeout=20000)
                item.evaluate.assert_not_called()

    def test_unknown_send_remains_sending_until_publication_is_verified(self):
        task={'id':5,'name':'讨论','kind':'discussion','status':'incomplete'}
        saved={'history':{'5':{'status':'sending','reply':'已有待核验回复'}}}
        request={'kind':'discussion','request_id':'fingerprint','topic':'主题'}
        page=Mock()
        page.url='https://www.xuetangx.com/learn/space/course/discussion/5'
        page.locator.return_value.count.return_value=1

        def check_unresolved_send(page,task,reply,saved,statefile):
            self.assertEqual(saved['history']['5']['status'],'sending')
            raise ValueError('上次发送结果不明')

        with tempfile.TemporaryDirectory() as root:
            reports=Path(root)
            folder=reports/'workflow_ai'/'5'
            folder.mkdir(parents=True)
            (folder/'response.json').write_text(json.dumps({
                'kind':'discussion','request_id':'fingerprint','reply':'已有待核验回复'
            },ensure_ascii=False),encoding='utf-8')
            with patch.object(workflow,'REPORTS',reports), \
                 patch.object(workflow,'wait_for_manual_verification'), \
                 patch.object(workflow,'own_nickname',return_value='test-account'), \
                 patch.object(workflow,'prepare_ai',return_value=request), \
                 patch.object(workflow,'publish_discussion',side_effect=check_unresolved_send):
                with self.assertRaisesRegex(ValueError,'上次发送结果不明'):
                    workflow.execute_task(page,saved,reports/'state.json',task,time.monotonic()+30)


if __name__=='__main__':unittest.main()
