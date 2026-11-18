import sys
import unittest
import time
from unittest.mock import patch
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from browser_checks import require_no_captcha, wait_for_manual_verification


class BrowserChecksTests(unittest.TestCase):
    def setUp(self):
        self.popup_patch=patch('browser_checks.notify_captcha')
        self.popup=self.popup_patch.start()
        self.addCleanup(self.popup_patch.stop)

    def test_offscreen_transparent_residue_is_not_a_challenge(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page()
                page.set_content('<div id="tcaptcha_transform_dy" style="width:300px;height:155px;position:absolute;top:-1000000px;opacity:0"><iframe src="about:blank#captcha"></iframe></div>')
                require_no_captcha(page)
                self.popup.assert_not_called()
            finally:browser.close()

    def test_waits_for_user_without_clicking_or_reloading(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page()
                page.set_content('''<div id="tcaptcha_transform_dy" style="width:360px;height:360px">
                  <button onclick="window.clicked=true">确定</button></div>
                  <script>window.clicked=false;setTimeout(()=>document.querySelector('#tcaptcha_transform_dy').remove(),100);</script>''')
                wait_for_manual_verification(page,time.monotonic()+3,stable_seconds=0.05,poll_ms=20)
                self.popup.assert_called_once()
                self.assertFalse(page.evaluate('window.clicked'))
                self.assertEqual(page.url,'about:blank')
                self.popup.reset_mock()
                page.set_content('<div id="tcaptcha_transform_dy">仍需人工验证</div>')
                with self.assertRaisesRegex(ValueError,'人工'):
                    wait_for_manual_verification(page,time.monotonic()+0.05,poll_ms=20)
            finally:browser.close()

    def test_visible_challenge_requires_manual_action_without_clicking(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page()
                page.set_content('''<div id="tcaptcha_transform_dy" style="width:360px;height:360px">
                    <button onclick="window.clicked=true">确定</button></div>
                    <script>window.clicked=false;</script>''')
                with self.assertRaisesRegex(ValueError,'人工'):
                    require_no_captcha(page)
                self.assertFalse(page.evaluate('window.clicked'))
                page.locator('#tcaptcha_transform_dy').evaluate("e=>e.style.display='none'")
                require_no_captcha(page)
                page.set_content('<video></video>')
                require_no_captcha(page)
            finally:
                browser.close()


if __name__=='__main__':unittest.main()
