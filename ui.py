"""
简单的 tkinter 测试 ui
"""
import asyncio
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import font, ttk
    from PIL import ImageTk
except ModuleNotFoundError as exc:
    raise SystemExit(
        "tkinter is not installed in this Python. Install the system package first, "
        "for example: sudo apt install python3-tk"
    ) from exc

from core import CloudGame, CloudGameCallbacks, QUEUE_TYPE_COIN, QUEUE_TYPE_NORMAL, configure_logging
from core.config import loads_json_with_comments
from core.models import CloudGameConfig


class UiConfig:
    GAME_VIEW_WIDTH = 1920
    GAME_VIEW_HEIGHT = 1080
    SIDEBAR_WIDTH = 390
    AUTO_CLICK_INTERVAL_MS = 1000
    AUTO_CLICK_HOLD_MS = 80


@dataclass
class UiSettings:
    finish_result: str = "finish_result.json"
    seconds: int = 0
    max_polls: int = 3000
    queue_type: str = ""
    node: str = ""
    speed_client_type: int = 7
    ws_payload_limit: int = 2048
    control_json: str = ""
    click: str = ""
    auto_click: bool = False
    core_config: str = "client_profile.json"


class KeyTranslator:
    KEYSYM_TO_VK = {
    "BackSpace": 8,
    "Tab": 9,
    "ISO_Left_Tab": 9,
    "Return": 13,
    "Shift_L": 16,
    "Shift_R": 16,
    "Control_L": 17,
    "Control_R": 17,
    "Alt_L": 18,
    "Alt_R": 18,
    "Escape": 27,
    "space": 32,
    "Prior": 33,
    "Next": 34,
    "End": 35,
    "Home": 36,
    "Left": 37,
    "Up": 38,
    "Right": 39,
    "Down": 40,
    "Insert": 45,
    "Delete": 46,
    "KP_Multiply": 106,
    "KP_Add": 107,
    "KP_Subtract": 109,
    "KP_Decimal": 110,
    "KP_Divide": 111,
    "Num_Lock": 144,
    "Caps_Lock": 20,
    "Scroll_Lock": 145,
    "semicolon": 186,
    "colon": 186,
    "equal": 187,
    "plus": 187,
    "comma": 188,
    "less": 188,
    "minus": 189,
    "underscore": 189,
    "period": 190,
    "greater": 190,
    "slash": 191,
    "question": 191,
    "grave": 192,
    "asciitilde": 192,
    "bracketleft": 219,
    "braceleft": 219,
    "backslash": 220,
    "bar": 220,
    "bracketright": 221,
    "braceright": 221,
    "apostrophe": 222,
    "quotedbl": 222,
    "exclam": 49,
    "at": 50,
    "numbersign": 51,
    "dollar": 52,
    "percent": 53,
    "asciicircum": 54,
    "ampersand": 55,
    "asterisk": 56,
    "parenleft": 57,
    "parenright": 48,
    }

    MODIFIER_KEYSYM_TO_VKS = {
        "Shift_L": [16, 160],
        "Shift_R": [16, 161],
        "Control_L": [17, 162],
        "Control_R": [17, 163],
        "Alt_L": [18, 164],
        "Alt_R": [18, 165],
    }

    @classmethod
    def from_tk_event(cls, event) -> list[int]:
        """把 Tk 键盘事件转换为云游戏使用的虚拟键码。"""
        keysym = event.keysym or ""
        if keysym in cls.MODIFIER_KEYSYM_TO_VKS:
            return cls.MODIFIER_KEYSYM_TO_VKS[keysym]
        if keysym in cls.KEYSYM_TO_VK:
            return [cls.KEYSYM_TO_VK[keysym]]
        if keysym.startswith("F") and keysym[1:].isdigit():
            number = int(keysym[1:])
            if 1 <= number <= 24:
                return [111 + number]
        if keysym.startswith("KP_") and keysym[3:].isdigit():
            return [96 + int(keysym[3:])]
        if len(keysym) == 1:
            char = keysym.upper()
            if "A" <= char <= "Z" or "0" <= char <= "9":
                return [ord(char)]
        return []


class CloudGameTkApp:
    def __init__(self, root: tk.Tk, settings: UiSettings):
        """初始化实例并保存运行所需的状态。"""
        self.root = root
        self.settings = settings
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.current_photo = None
        self.video_image_id = None
        self.core: CloudGame | None = None
        self.input_ready = False
        self.video_source_size = (0, 0)
        self.video_display_size = (0, 0)
        self.video_display_origin = (0, 0)
        self.pressed_keys: set[int] = set()
        self.last_mouse_pos: tuple[float, float] | None = None
        self.last_mouse_move_at = 0.0
        self.running = False
        self.auto_click_enabled = self.settings.auto_click
        self.auto_click_scheduled = False
        self.auto_click_seq = 0
        self.last_auto_click_skip_at = 0.0
        self.last_finish_result: dict | None = None
        self.root_dir = Path(__file__).resolve().parent
        self.queue_type_var = tk.StringVar(value=self.settings.queue_type or QUEUE_TYPE_NORMAL)
        self.auto_click_var = tk.BooleanVar(value=bool(self.settings.auto_click))

        root.title("Cloud RTC Game Viewer")
        root.geometry("1360x780")
        root.minsize(960, 560)

        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self._drain_events)

    def _build_layout(self) -> None:
        """创建主窗口布局和控件。"""
        self.root.configure(bg="#0f1115")

        style = ttk.Style(self.root)
        style.configure("Panel.TFrame", background="#0f1115")
        style.configure("Surface.TFrame", background="#151922")
        style.configure("Title.TLabel", background="#151922", foreground="#e6edf3", font=("", 10, "bold"))
        style.configure("Muted.TLabel", background="#151922", foreground="#8b949e")
        style.configure("Status.TLabel", background="#0f1115", foreground="#c9d1d9")

        toolbar = ttk.Frame(self.root, padding=(10, 8))
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="finish_result").pack(side=tk.LEFT)
        self.finish_var = tk.StringVar(value=self.settings.finish_result)
        ttk.Entry(toolbar, textvariable=self.finish_var, width=36).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(toolbar, text="seconds").pack(side=tk.LEFT)
        self.seconds_var = tk.StringVar(value=str(self.settings.seconds))
        ttk.Entry(toolbar, textvariable=self.seconds_var, width=8).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(toolbar, text="payload limit").pack(side=tk.LEFT)
        self.payload_limit_var = tk.StringVar(value=str(self.settings.ws_payload_limit))
        ttk.Entry(toolbar, textvariable=self.payload_limit_var, width=8).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(toolbar, text="队列").pack(side=tk.LEFT)
        self.free_queue_radio = ttk.Radiobutton(
            toolbar,
            text="免费",
            variable=self.queue_type_var,
            value=QUEUE_TYPE_NORMAL,
        )
        self.free_queue_radio.pack(side=tk.LEFT, padx=(6, 2))
        self.coin_queue_radio = ttk.Radiobutton(
            toolbar,
            text="星云币",
            variable=self.queue_type_var,
            value=QUEUE_TYPE_COIN,
        )
        self.coin_queue_radio.pack(side=tk.LEFT, padx=(2, 12))

        self.full_btn = ttk.Button(toolbar, text="Dispatch + Start", command=self.dispatch_and_start)
        self.full_btn.pack(side=tk.LEFT, padx=4)
        self.dispatch_btn = ttk.Button(toolbar, text="Dispatch Only", command=self.dispatch_only)
        self.dispatch_btn.pack(side=tk.LEFT, padx=4)
        self.start_btn = ttk.Button(toolbar, text="Connect Only", command=self.connect_only)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(toolbar, text="Stop", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        self.auto_click_check = ttk.Checkbutton(
            toolbar,
            text="Auto Click",
            variable=self.auto_click_var,
            command=self._toggle_auto_click,
        )
        self.auto_click_check.pack(side=tk.LEFT, padx=(8, 0))

        body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        self.video_frame = ttk.Frame(body, padding=(10, 8), style="Panel.TFrame")
        video_header = ttk.Frame(self.video_frame, padding=(0, 0, 0, 6), style="Panel.TFrame")
        video_header.pack(fill=tk.X)
        ttk.Label(video_header, text="Game", style="Title.TLabel").pack(side=tk.LEFT)
        self.focus_var = tk.StringVar(value="auto center click: off")
        self.mouse_pos_var = tk.StringVar(value="x=-- y=--")
        video_status = ttk.Frame(video_header, style="Panel.TFrame")
        video_status.pack(side=tk.RIGHT)
        ttk.Label(video_status, textvariable=self.focus_var, style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(video_status, textvariable=self.mouse_pos_var, style="Muted.TLabel").pack(side=tk.LEFT)

        self.video_canvas = tk.Canvas(
            self.video_frame,
            bg="#05070a",
            bd=0,
            highlightthickness=2,
            highlightbackground="#222833",
            highlightcolor="#4db3ff",
            cursor="crosshair",
            takefocus=True,
        )
        self.video_canvas.pack(fill=tk.BOTH, expand=True)
        self.placeholder_id = self.video_canvas.create_text(
            0,
            0,
            text="No video",
            fill="#6e7681",
            font=("", 14),
        )
        self._bind_input_events()
        body.add(self.video_frame, weight=5)

        log_frame = ttk.Frame(body, width=UiConfig.SIDEBAR_WIDTH, padding=(8, 8, 10, 8), style="Surface.TFrame")
        log_header = ttk.Frame(log_frame, padding=(0, 0, 0, 6), style="Surface.TFrame")
        log_header.pack(fill=tk.X)
        ttk.Label(log_header, text="WebSocket", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(log_header, text="data stream", style="Muted.TLabel").pack(side=tk.RIGHT)

        log_font = font.Font(family="TkFixedFont", size=9)
        log_body = ttk.Frame(log_frame, style="Surface.TFrame")
        log_body.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(
            log_body,
            wrap=tk.NONE,
            width=46,
            bg="#0b0f14",
            fg="#d0d7de",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            font=log_font,
            padx=8,
            pady=8,
        )
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_body, orient=tk.VERTICAL, command=self.log.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.tag_configure("send", foreground="#4db3ff")
        self.log.tag_configure("recv", foreground="#ff4dd2")
        self.log.tag_configure("status", foreground="#bbbbbb")
        self.log.tag_configure("error", foreground="#ff5f5f")
        self.log.tag_configure("input", foreground="#7ee787")

        text_tools = ttk.Frame(log_frame, padding=(0, 8, 0, 0), style="Surface.TFrame")
        text_tools.pack(fill=tk.X)
        self.text_input_var = tk.StringVar()
        self.text_input = ttk.Entry(text_tools, textvariable=self.text_input_var)
        self.text_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.text_input.bind("<Return>", self._send_text_input)
        self.send_text_btn = ttk.Button(text_tools, text="Send", command=self._send_text_input)
        self.send_text_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.paste_text_btn = ttk.Button(text_tools, text="Paste", command=self._paste_remote_clipboard)
        self.paste_text_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.sync_clipboard_btn = ttk.Button(text_tools, text="Sync", command=self._sync_clipboard_text)
        self.sync_clipboard_btn.pack(side=tk.LEFT, padx=(6, 0))
        body.add(log_frame, weight=1)
        self.root.after_idle(lambda: body.sashpos(0, max(620, self.root.winfo_width() - UiConfig.SIDEBAR_WIDTH)))

        self.status_var = tk.StringVar(value="idle")
        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 5), style="Status.TLabel").pack(fill=tk.X)

    def _set_running(self, running: bool) -> None:
        """切换运行状态和按钮可用性。"""
        self.running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.full_btn.configure(state=state)
        self.dispatch_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.free_queue_radio.configure(state=state)
        self.coin_queue_radio.configure(state=state)
        self.stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.auto_click_check.configure(state=tk.NORMAL)
        if running:
            self.auto_click_enabled = bool(self.auto_click_var.get())
            if self.auto_click_enabled:
                self.events.put(("input", "AUTO CLICK waiting: center=(960,540), interval=1000ms\n"))
                self.events.put(("input_ready", None))
        else:
            self.auto_click_enabled = False
            self.auto_click_scheduled = False
            self.input_ready = False
            self.core = None
            self.pressed_keys.clear()
            self.focus_var.set("auto center click: off")

    def _toggle_auto_click(self) -> None:
        """同步自动点击勾选状态，并在运行中按需触发。"""
        enabled = bool(self.auto_click_var.get())
        self.settings.auto_click = enabled
        self.auto_click_enabled = enabled
        if not enabled:
            self.focus_var.set("focused" if self.video_canvas.focus_get() is self.video_canvas else "auto center click: off")
            self.events.put(("input", "AUTO CLICK disabled\n"))
            return
        self.events.put(("input", "AUTO CLICK enabled\n"))
        if self.running and self.input_ready:
            self.focus_var.set("auto center click active")
            self._schedule_auto_click(0)

    def _bind_input_events(self) -> None:
        """绑定画布上的鼠标键盘事件。"""
        self.video_frame.bind("<ButtonPress>", self._focus_video)
        self.video_canvas.bind("<ButtonPress-1>", lambda event: self._on_mouse_button(event, "left", True))
        self.video_canvas.bind("<ButtonRelease-1>", lambda event: self._on_mouse_button(event, "left", False))
        self.video_canvas.bind("<ButtonPress-2>", lambda event: self._on_mouse_button(event, "middle", True))
        self.video_canvas.bind("<ButtonRelease-2>", lambda event: self._on_mouse_button(event, "middle", False))
        self.video_canvas.bind("<ButtonPress-3>", lambda event: self._on_mouse_button(event, "right", True))
        self.video_canvas.bind("<ButtonRelease-3>", lambda event: self._on_mouse_button(event, "right", False))
        self.video_canvas.bind("<Motion>", self._on_mouse_move)
        self.video_canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.video_canvas.bind("<Button-4>", lambda event: self._send_scroll(120))
        self.video_canvas.bind("<Button-5>", lambda event: self._send_scroll(-120))
        self.video_canvas.bind("<KeyPress>", self._on_key_down)
        self.video_canvas.bind("<KeyRelease>", self._on_key_up)
        self.video_canvas.bind("<FocusIn>", self._on_focus_in)
        self.video_canvas.bind("<FocusOut>", self._on_focus_out)
        self.video_canvas.bind("<Configure>", self._on_video_resize)
        self.video_canvas.bind("<Leave>", self._on_mouse_leave)

    def _set_input_ready(self, ready: bool) -> None:
        """更新输入状态。"""
        self.input_ready = ready
        self.events.put(("status", "input ready" if ready else "input closed"))
        if not ready:
            self.events.put(("input", "input stopped: rtc worker ended\n"))
        elif self.auto_click_enabled:
            self.events.put(("input", "AUTO CLICK input ready\n"))
        else:
            self.events.put(("input", "input ready\n"))
        if ready and self.auto_click_enabled:
            self.events.put(("input_ready", None))

    def _send_input(self, action: dict) -> bool:
        """发送一个 UI 输入动作。"""
        if not self.input_ready or self.core is None:
            return False
        return self.core.send_input(action)

    def _send_key_sequence(self, actions: tuple[dict, ...], interval_ms: int = 35) -> bool:
        """按固定间隔发送一组键盘动作。"""
        if not self.input_ready or self.core is None:
            return False

        def send_at(index: int) -> None:
            """发送指定位置的键盘动作并安排下一步。"""
            if index >= len(actions):
                return
            self._send_input(actions[index])
            self.root.after(interval_ms, lambda: send_at(index + 1))

        send_at(0)
        return True

    def _get_clipboard_text(self) -> str:
        """在 UI 主线程读取本机剪贴板。"""
        if threading.current_thread() is threading.main_thread():
            try:
                return self.root.clipboard_get()
            except tk.TclError:
                return ""

        result: queue.Queue[object] = queue.Queue(maxsize=1)

        def read_clipboard() -> None:
            """读取剪贴板并把结果交回工作线程。"""
            try:
                result.put(self.root.clipboard_get())
            except tk.TclError:
                result.put("")
            except Exception as exc:
                result.put(exc)

        self.root.after(0, read_clipboard)
        value = result.get(timeout=3.0)
        if isinstance(value, Exception):
            raise value
        return str(value)

    def _send_text_input(self, _event=None) -> str:
        """发送输入框中的 IME 文本。"""
        text = self.text_input_var.get()
        if not text:
            return "break"
        if self._send_input({"type": "ime", "text": text}):
            self.events.put(("input", f"IME text sent chars={len(text)}\n"))
        else:
            self.events.put(("input", "IME text skipped: input channel not ready\n"))
        return "break"

    def _paste_remote_clipboard(self) -> str:
        """在云端执行 Ctrl+V 粘贴。"""
        actions = (
            {"type": "key_down", "key_code": 17},
            {"type": "key_down", "key_code": 162},
            {"type": "key_down", "key_code": 86},
            {"type": "key_up", "key_code": 86},
            {"type": "key_up", "key_code": 162},
            {"type": "key_up", "key_code": 17},
        )
        if not self._send_key_sequence(actions):
            self.events.put(("input", "paste skipped: input channel not ready\n"))
            return "break"
        self.events.put(("input", "remote paste sent: Ctrl+V\n"))
        return "break"

    def _sync_clipboard_text(self) -> str:
        """读取本机剪贴板并发送到云端剪贴板。"""
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self.events.put(("input", "clipboard skipped: local clipboard is empty\n"))
            return "break"
        if not text:
            self.events.put(("input", "clipboard skipped: local clipboard is empty\n"))
            return "break"
        self.text_input_var.set(text)
        if self._send_input({"type": "clipboard", "text": text}):
            self.events.put(("input", f"clipboard text sent chars={len(text)}\n"))
        else:
            self.events.put(("input", "clipboard skipped: input channel not ready\n"))
        return "break"

    def _focus_video(self, _event=None) -> str:
        """让视频画布获得键盘焦点。"""
        self.video_canvas.focus_set()
        self.focus_var.set("focused; auto center click active" if self.auto_click_enabled else "focused")
        self.video_canvas.configure(highlightbackground="#4db3ff")
        return "break"

    def _auto_click_center(self) -> None:
        """按配置向画面中心发送一次自动点击。"""
        self.auto_click_scheduled = False
        if not self.running or not self.auto_click_enabled:
            return
        if not self.input_ready:
            now = time.monotonic()
            if now - self.last_auto_click_skip_at >= 2.0:
                self.last_auto_click_skip_at = now
                self.events.put(("input", "AUTO CLICK skipped: input channel not ready\n"))
            self._schedule_auto_click(UiConfig.AUTO_CLICK_INTERVAL_MS)
            return

        self.auto_click_seq += 1
        x = UiConfig.GAME_VIEW_WIDTH / 2
        y = UiConfig.GAME_VIEW_HEIGHT / 2
        self.last_mouse_pos = (x, y)
        self._send_input({"type": "move", "x": x, "y": y, "dx": 0, "dy": 0})
        self._send_input({"type": "down", "button": "left", "x": x, "y": y})
        self.events.put(("input", f"AUTO CLICK #{self.auto_click_seq} down x={x:.0f} y={y:.0f} button=left\n"))
        self.root.after(UiConfig.AUTO_CLICK_HOLD_MS, lambda: self._auto_click_center_up(x, y, self.auto_click_seq))
        self._schedule_auto_click(UiConfig.AUTO_CLICK_INTERVAL_MS)

    def _schedule_auto_click(self, delay_ms: int = 0) -> None:
        """安排下一次自动点击任务。"""
        if self.auto_click_scheduled:
            return
        self.auto_click_scheduled = True
        self.root.after(delay_ms, self._auto_click_center)

    def _auto_click_center_up(self, x: float, y: float, seq: int) -> None:
        """发送自动点击的释放事件。"""
        if not self.running or not self.auto_click_enabled or not self.input_ready:
            return
        self._send_input({"type": "up", "button": "left", "x": x, "y": y})
        self.events.put(("input", f"AUTO CLICK #{seq} up   x={x:.0f} y={y:.0f} button=left\n"))

    def _event_to_game_xy(self, event) -> tuple[float, float, float, float] | None:
        """把画布坐标转换为游戏归一化坐标。"""
        source_w, source_h = self.video_source_size
        display_w, display_h = self.video_display_size
        if source_w <= 0 or source_h <= 0 or display_w <= 0 or display_h <= 0:
            return None
        left, top = self.video_display_origin
        local_x = event.x - left
        local_y = event.y - top
        if local_x < 0 or local_y < 0 or local_x > display_w or local_y > display_h:
            return None
        return (
            max(0.0, min(1.0, local_x / display_w)),
            max(0.0, min(1.0, local_y / display_h)),
            local_x,
            local_y,
        )

    def _set_mouse_position(self, pos: tuple[float, float, float, float] | None) -> None:
        """更新标题栏里的归一化鼠标坐标。"""
        if pos is None:
            self.mouse_pos_var.set("x=-- y=--")
            return
        self.mouse_pos_var.set(f"x={pos[0]:.4f} y={pos[1]:.4f}")

    def _on_mouse_leave(self, _event) -> None:
        """鼠标离开视频画面时清空坐标显示。"""
        self._set_mouse_position(None)

    def _on_mouse_move(self, event) -> None:
        """处理鼠标移动并发送游戏坐标。"""
        pos = self._event_to_game_xy(event)
        self._set_mouse_position(pos)
        if pos is None:
            return
        now = time.monotonic()
        if now - self.last_mouse_move_at < 0.01:
            return
        dx = dy = 0.0
        if self.last_mouse_pos is not None:
            dx = pos[2] - self.last_mouse_pos[0]
            dy = pos[3] - self.last_mouse_pos[1]
        self.last_mouse_pos = (pos[2], pos[3])
        self.last_mouse_move_at = now
        self._send_input({"type": "move", "x": pos[0], "y": pos[1], "dx": dx, "dy": dy})

    def _on_mouse_button(self, event, button: str, is_down: bool) -> None:
        """处理鼠标按键并发送按下/释放动作。"""
        self._focus_video()
        pos = self._event_to_game_xy(event)
        self._set_mouse_position(pos)
        if pos is None:
            return "break"
        self.last_mouse_pos = (pos[2], pos[3])
        self._send_input({"type": "down" if is_down else "up", "button": button, "x": pos[0], "y": pos[1]})
        return "break"

    def _on_mouse_wheel(self, event) -> None:
        """处理鼠标滚轮事件。"""
        delta = int(event.delta)
        if delta:
            self._send_scroll(delta)
        return "break"

    def _send_scroll(self, delta: int) -> None:
        """发送滚轮输入动作。"""
        self._focus_video()
        self._send_input({"type": "scroll", "delta": delta})
        return "break"

    def _on_key_down(self, event) -> str:
        """处理键盘按下并避免重复发送。"""
        key_codes = KeyTranslator.from_tk_event(event)
        if not key_codes:
            return "break"
        capslock = bool(event.state & 0x0002)
        numlock = bool(event.state & 0x0010)
        for key_code in key_codes:
            if key_code in self.pressed_keys:
                continue
            self.pressed_keys.add(key_code)
            self._send_input({
                "type": "key_down",
                "key_code": key_code,
                "capslock": capslock,
                "numlock": numlock,
            })
        return "break"

    def _on_key_up(self, event) -> str:
        """处理键盘释放并同步按键状态。"""
        key_codes = KeyTranslator.from_tk_event(event)
        capslock = bool(event.state & 0x0002)
        numlock = bool(event.state & 0x0010)
        for key_code in key_codes:
            self.pressed_keys.discard(key_code)
            self._send_input({
                "type": "key_up",
                "key_code": key_code,
                "capslock": capslock,
                "numlock": numlock,
            })
        return "break"

    def _on_focus_in(self, _event) -> None:
        """处理画布获得焦点时的界面状态。"""
        self.focus_var.set("focused")
        self.video_canvas.configure(highlightbackground="#4db3ff")

    def _on_focus_out(self, _event) -> None:
        """处理画布失焦并释放已按下按键。"""
        for key_code in list(self.pressed_keys):
            self._send_input({"type": "key_up", "key_code": key_code})
        self.pressed_keys.clear()
        self.focus_var.set("auto center click active" if self.auto_click_enabled else "auto center click: off")
        self.video_canvas.configure(highlightbackground="#222833")

    def dispatch_and_start(self) -> None:
        """启动调度并连接流程。"""
        self._start_worker("full")

    def dispatch_only(self) -> None:
        """只启动调度流程。"""
        self._start_worker("dispatch")

    def connect_only(self) -> None:
        """只启动连接流程。"""
        self._start_worker("connect")

    def _start_worker(self, mode: str) -> None:
        """启动后台工作线程。"""
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self._set_running(True)
        self._append_log("status", f"{mode} started\n")

        self.worker = threading.Thread(target=self._worker_main, args=(mode,), daemon=False)
        self.worker.start()

    def stop(self) -> None:
        """请求后台流程停止。"""
        self.stop_event.set()
        self._append_log("status", "stop requested\n")

    def on_close(self) -> None:
        """处理窗口关闭并等待后台线程退出。"""
        self.auto_click_enabled = False
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self._set_running(False)
            self.status_var.set("stopping")
            self._append_log("status", "closing: waiting for worker to stop\n")
            self.root.after(100, self._finish_close)
            return
        self.root.destroy()

    def _finish_close(self) -> None:
        """等待后台线程结束后销毁窗口。"""
        if self.worker and self.worker.is_alive():
            self.root.after(100, self._finish_close)
            return
        self.root.destroy()

    def _worker_main(self, mode: str) -> None:
        """在线程中执行调度或连接任务。"""
        try:
            if mode in ("full", "dispatch"):
                self._run_dispatch()
            if mode in ("full", "connect") and not self.stop_event.is_set():
                self._run_rtc(use_latest_result=mode == "full")
            self.events.put(("status", "finished"))
        except Exception as exc:
            self.events.put(("error", repr(exc)))
        finally:
            self.events.put(("done", None))

    def _create_core(self) -> CloudGame:
        """根据界面输入创建 CloudGame 实例, 并校验登录态。"""
        config = CloudGameConfig(
            max_seconds=int(self.seconds_var.get()),
            max_polls=self.settings.max_polls,
            queue_type=self.queue_type_var.get(),
            node=self.settings.node,
            speed_client_type=self.settings.speed_client_type,
            snapshot_dir=str(self.root_dir),
            snapshot_interval=20,
            video_frame_interval=0.1,
            control_actions=CloudGame.load_actions(self.settings.control_json or None, self.settings.click or None),
            ws_log_payload=True,
            ws_payload_limit=int(self.payload_limit_var.get()),
            color=False,
            clipboard_getter=self._get_clipboard_text,
            core_config=self._load_core_config(),
            root_dir=self.root_dir,
        )
        core = CloudGame(
            config=config,
            qr_dir=self.root_dir / "log",
            callbacks=CloudGameCallbacks(
                on_status=lambda message, level: self.events.put(("status", (message, level))),
                on_dispatch_log=lambda line, level: self.events.put(("dispatch", (line, level))),
                on_video_frame=lambda image, count: self.events.put(("video", (image, count))),
                on_ws_event=lambda event: self.events.put(("ws", event)),
                on_input_ready=self._set_input_ready,
            ),
        )
        # 每次创建都通过 load_credentials 重新读 credentials.json：用户在另一终端
        # 跑 qrcode_login.py 重登后, 不重启 UI, 下一次 Dispatch 也能拿到新凭据。
        # GUI 没法在工作线程里阻塞等终端扫码 → auto_login=False, 失效时抛
        # RuntimeError 由 _worker_main 转写到状态栏, 提示用户去命令行登录后再试。
        core.load_credentials(self.root_dir / "credentials.json")
        try:
            core.ensure_login(auto_login=False)
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc}; 请在命令行运行 `python qrcode_login.py login` 重新登录后再试"
            ) from exc
        return core

    @staticmethod
    def _format_wallet_summary(wallet: dict) -> str:
        """把钱包摘要压缩成一行 UI 日志。"""
        summary = wallet.get("summary") or {}
        return (
            "wallet: "
            f"coin={summary.get('coin_num')} "
            f"coin_minutes={summary.get('coin_minutes')} "
            f"free_minutes={summary.get('free_time_minutes')} "
            f"play_card_sec={summary.get('play_card_remaining_sec')}"
        )

    @staticmethod
    def _format_queue_summary(queue_info: dict, queue_type: str) -> str:
        """把普通/星云币队列摘要压缩成一行 UI 日志。"""
        key = "coin" if queue_type == QUEUE_TYPE_COIN else "normal"
        label = "coin" if queue_type == QUEUE_TYPE_COIN else "free"
        selected = queue_info.get(key) or {}
        normal = queue_info.get("normal") or {}
        coin = queue_info.get("coin") or {}
        return (
            f"queue estimate: selected={label} "
            f"waiting_min={selected.get('waiting_time_min')} "
            f"rank={selected.get('queue_rank')} "
            f"len={selected.get('queue_len') or selected.get('queue_length')} "
            f"free_wait={normal.get('waiting_time_min')} "
            f"coin_wait={coin.get('waiting_time_min')}"
        )

    def _load_core_config(self) -> dict | None:
        """读取可选的 core 配置文件。"""
        path = Path(self.settings.core_config)
        path = path if path.is_absolute() else self.root_dir / path
        if not path.exists():
            return None
        try:
            return loads_json_with_comments(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RuntimeError(f"core config must be a JSON object: {path}") from exc

    def _run_dispatch(self) -> None:
        """执行调度并保存结果。"""
        core = self._create_core()
        queue_type = self.queue_type_var.get()
        queue_label = "星云币" if queue_type == QUEUE_TYPE_COIN else "免费"
        self.events.put(("dispatch", (f"pre-dispatch check started: queue={queue_label}", logging.INFO)))
        wallet = core.get_wallet_info()
        self.events.put(("dispatch", (self._format_wallet_summary(wallet), logging.INFO)))
        queue_info = core.get_queue_estimate()
        self.events.put(("dispatch", (self._format_queue_summary(queue_info, queue_type), logging.INFO)))
        result = core.dispatch(stop_event=self.stop_event)
        self.last_finish_result = result
        self._save_finish_result(result)

    def _finish_result_path(self) -> Path:
        """解析 finish_result 文件路径。"""
        path = Path(self.finish_var.get())
        return path if path.is_absolute() else self.root_dir / path

    def _save_finish_result(self, result: dict) -> None:
        """保存调度完成结果。"""
        path = self._finish_result_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.events.put(("dispatch", (f"finish_result saved for reconnect: {path}", logging.INFO)))

    def _run_rtc(self, *, use_latest_result: bool = False) -> None:
        """读取调度结果并启动 RTC 会话。"""
        core = self._create_core()
        self.core = core
        finish_result = self.last_finish_result if use_latest_result else self._load_finish_result()
        try:
            asyncio.run(core.connect(
                finish_result=finish_result,
                stop_event=self.stop_event,
            ))
        finally:
            self.input_ready = False
            self.core = None

    def _load_finish_result(self) -> dict:
        """从文件读取调度完成结果。"""
        path = self._finish_result_path()
        result = json.loads(path.read_text(encoding="utf-8"))
        self.last_finish_result = result
        self.events.put(("dispatch", (f"finish_result loaded for reconnect: {path}", logging.INFO)))
        return result

    @staticmethod
    def _log_payload(payload) -> tuple[str, int]:
        """兼容旧队列 payload，并提取日志文本和级别。"""
        if isinstance(payload, tuple) and len(payload) == 2:
            message, level = payload
            return str(message), int(level)
        return str(payload), logging.INFO

    @staticmethod
    def _tag_for_level(level: int) -> str:
        """按日志级别选择 Text tag。"""
        if level >= logging.ERROR:
            return "error"
        if level >= logging.WARNING:
            return "error"
        return "status"

    def _drain_events(self) -> None:
        """从线程事件队列刷新界面。"""
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "video":
                    self._show_video(*payload)
                elif kind == "ws":
                    self._show_ws(payload)
                elif kind == "status":
                    message, level = self._log_payload(payload)
                    self.status_var.set(message)
                    self._append_log(self._tag_for_level(level), f"{message}\n")
                elif kind == "input":
                    self._append_log("input", str(payload))
                elif kind == "input_ready":
                    self.focus_var.set("auto center click active")
                    self._schedule_auto_click(0)
                elif kind == "dispatch":
                    message, level = self._log_payload(payload)
                    self._append_log(self._tag_for_level(level), f"[dispatch] {message}\n")
                elif kind == "error":
                    self.status_var.set(str(payload))
                    self._append_log("error", f"{payload}\n")
                elif kind == "done":
                    self._set_running(False)
        except queue.Empty:
            pass
        self.root.after(50, self._drain_events)

    def _show_video(self, image, count: int) -> None:
        """在画布上显示最新视频帧。"""
        max_w = max(320, self.video_canvas.winfo_width())
        max_h = max(240, self.video_canvas.winfo_height())
        display = image.copy()
        display.thumbnail((max_w, max_h))
        self.video_source_size = (image.width, image.height)
        self.video_display_size = display.size
        self.current_photo = ImageTk.PhotoImage(display)
        self._draw_video_image()
        self.status_var.set(f"video frame {count} {image.width}x{image.height}")

    def _draw_video_image(self) -> None:
        """按画布尺寸居中绘制视频帧。"""
        if self.current_photo is None:
            width = max(1, self.video_canvas.winfo_width())
            height = max(1, self.video_canvas.winfo_height())
            self.video_canvas.coords(self.placeholder_id, width / 2, height / 2)
            return
        canvas_w = max(1, self.video_canvas.winfo_width())
        canvas_h = max(1, self.video_canvas.winfo_height())
        display_w, display_h = self.video_display_size
        left = max(0, int((canvas_w - display_w) / 2))
        top = max(0, int((canvas_h - display_h) / 2))
        self.video_display_origin = (left, top)
        self.video_canvas.coords(self.placeholder_id, -1000, -1000)
        if self.video_image_id is None:
            self.video_image_id = self.video_canvas.create_image(left, top, anchor=tk.NW, image=self.current_photo)
        else:
            self.video_canvas.itemconfigure(self.video_image_id, image=self.current_photo)
            self.video_canvas.coords(self.video_image_id, left, top)

    def _on_video_resize(self, _event) -> None:
        """画布尺寸变化时重绘视频帧。"""
        self._draw_video_image()

    def _show_ws(self, event: dict) -> None:
        """追加一条 WebSocket 日志。"""
        tag = "send" if event["direction"] == "SEND" else "recv"
        self._append_log(tag, f"[{event['time']}] WS {event['arrow']} {event['summary']}\n")
        for detail in event.get("details") or []:
            self._append_log(tag, f"{detail}\n")

    def _append_log(self, tag: str, text: str) -> None:
        """向日志窗口追加文本。"""
        self.log.insert(tk.END, text, tag)
        self.log.see(tk.END)

def main() -> None:
    """启动程序入口。"""
    configure_logging("INFO")
    root = tk.Tk()
    CloudGameTkApp(root, UiSettings())
    root.mainloop()


if __name__ == "__main__":
    main()
