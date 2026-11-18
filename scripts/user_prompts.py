"""Desktop prompts for the workflow operator."""
import sys
import threading

_popup_lock=threading.Lock()


def choose_runtime_seconds():
    import tkinter as tk
    from tkinter import simpledialog
    root=tk.Tk()
    root.withdraw()
    root.attributes('-topmost',True)
    try:
        minutes=simpledialog.askinteger(
            '本次运行时间',
            '请输入本次运行上限（分钟，1–1440）：\n等待人工验证也计入时间；到时在安全节点停止。\n取消则不启动工作流。',
            initialvalue=120,minvalue=1,maxvalue=1440,parent=root)
        return None if minutes is None else minutes*60
    finally:
        root.destroy()


def notify_captcha():
    """Show at most one native reminder, without blocking page observation."""
    if sys.platform!='win32' or not _popup_lock.acquire(blocking=False):
        return

    def show():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                '课程页面出现安全验证。\n请切换到专用 Chrome，手动完成页面中的验证。\n\n无需重启脚本，验证框消失后将自动继续。\n此提醒窗口本身不能完成验证。',
                '学堂在线：需要人工验证',
                0x00000040 | 0x00010000 | 0x00040000)
        except Exception as exc:
            print(f'弹窗提醒不可用，请查看浏览器中的验证：{exc}',flush=True)
        finally:
            _popup_lock.release()
    threading.Thread(target=show,name='captcha-reminder',daemon=True).start()
