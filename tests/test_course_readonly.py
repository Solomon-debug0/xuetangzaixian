import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from extract_course import check_login, extract_course_info


class CourseReadOnlyTests(unittest.TestCase):
    def test_read_course_with_real_playwright_page(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.set_content('<div class="course-action-learn-space"></div>')
                self.assertFalse(check_login(page))
                page.context.add_cookies([
                    {'name': 'k', 'value': 'test-user', 'url': 'https://www.xuetangx.com'},
                    {'name': 'cna', 'value': 'test-client', 'url': 'https://www.xuetangx.com'},
                ])
                page.evaluate("""() => {
                    document.querySelector('.course-action-learn-space').__vue__ = {
                        $data: {course_id: 123, classroomid: 456, course_sign: 'fixture'}
                    };
                }""")
                self.assertTrue(check_login(page))
                info = extract_course_info(page)
                self.assertEqual(info['course_id'], 123)
                self.assertEqual(info['user_id'], 'test-user')
                self.assertEqual(info['videos'], [])
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
