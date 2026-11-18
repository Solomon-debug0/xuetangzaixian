import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from user_prompts import choose_runtime_seconds
import workflow


class UserPromptTests(unittest.TestCase):
    def test_cancel_does_not_connect_browser(self):
        with patch.object(sys,'argv',['workflow.py','run']), \
             patch.object(workflow,'choose_runtime_seconds',return_value=None), \
             patch.object(workflow,'sync_playwright') as browser:
            workflow.main()
            browser.assert_not_called()

    def test_minutes_and_cancel(self):
        root=Mock()
        with patch('tkinter.Tk',return_value=root),patch('tkinter.simpledialog.askinteger',return_value=90):
            self.assertEqual(choose_runtime_seconds(),5400)
            root.destroy.assert_called_once()
        with patch('tkinter.Tk',return_value=Mock()),patch('tkinter.simpledialog.askinteger',return_value=None):
            self.assertIsNone(choose_runtime_seconds())


if __name__=='__main__':unittest.main()
