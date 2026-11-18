"""Recognize verification overlays and hand control back to the user."""
import time
from user_prompts import notify_captcha


def captcha_visible(page):
    return page.evaluate('''() => [...document.querySelectorAll('#tcaptcha_transform_dy, iframe[src*="captcha"]')].some(e => {
        const r=e.getBoundingClientRect();
        if(r.width<=0 || r.height<=0 || r.right<=0 || r.bottom<=0 || r.left>=innerWidth || r.top>=innerHeight)return false;
        for(let node=e;node;node=node.parentElement){
            const s=getComputedStyle(node);
            if(s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse' || Number(s.opacity)===0)return false;
        }
        return true;
    })''')


def require_no_captcha(page):
    if captcha_visible(page):
        raise ValueError('页面出现安全验证，请在浏览器中人工完成后恢复工作流。程序不会点击或代答验证码。')


def wait_for_manual_verification(page,deadline,stable_seconds=2,poll_ms=500):
    if not captcha_visible(page):
        return
    notify_captcha()
    print('等待人工安全验证：请在当前浏览器中完成验证；程序保持页面，不刷新、不点击验证码。',flush=True)
    clear_since=None
    while time.monotonic()<deadline:
        if captcha_visible(page):
            clear_since=None
        else:
            if clear_since is None:clear_since=time.monotonic()
            if time.monotonic()-clear_since>=stable_seconds:
                print('验证框已消失，恢复当前任务。',flush=True)
                return
        page.wait_for_timeout(poll_ms)
    raise ValueError('等待人工安全验证超时；当前页面和任务断点均保留。')
