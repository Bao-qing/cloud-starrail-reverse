"""米哈游通行证 (passport-api) 凭据管理。

本模块承载所有"通行证 SDK"相关的常量、纯工具函数与登录类，包括:

* 共享常量与请求头模板 —— 供 ``core.dispatcher`` 等模块复用 (但 dispatcher
  仅 import 工具函数, 不会引用 :class:`Authenticator`, 保持职责解耦)。
* :func:`parse_cookie_header` 等纯函数 —— 无副作用, 任何模块可直接调用。
* :class:`Authenticator` —— 二维码扫码登录 + cookie 有效性校验, 负责
  ``credentials.json`` 的读写。

设计要点:
    Dispatcher 自带 ``webVerifyForGame`` 调用是为了换 ``channel_token`` 走
    后续调度链, 与本模块 ``Authenticator.check`` 的"探活"语义不同, 因此
    两边 *不共享* 状态, 仅共享底层常量与 header 构造函数。
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from .log import get_logger


# ---------------------------------------------------------------------------
# 端点 / SDK 标识
# ---------------------------------------------------------------------------
PASSPORT_BASE = "https://passport-api.mihoyo.com"
CREATE_QR_URL = f"{PASSPORT_BASE}/account/ma-cn-passport/web/createQRLogin"
QUERY_QR_URL = f"{PASSPORT_BASE}/account/ma-cn-passport/web/queryQRLoginStatus"
WEB_VERIFY_URL = f"{PASSPORT_BASE}/account/ma-cn-session/web/webVerifyForGame"

PASSPORT_APP_ID = "c90mr1bwo2rk"
GAME_BIZ = "hkrpg_cn"
PASSPORT_SDK_VERSION = "2.53.1"
SESSION_SDK_VERSION = "2.50.1"  # webVerifyForGame 用的版本号略低

# ---------------------------------------------------------------------------
# 浏览器特征 (与 web-SDK 抓包一致)
# ---------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Not:A-Brand";v="99", "Google Chrome";v="149", "Chromium";v="149"'

PASSPORT_REFERER = (
    "https://user.mihoyo.com/login-platform/index.html"
    "?client_type=25&app_id=c90mr1bwo2rk&theme=rpg&token_type=4&game_biz=hkrpg_cn"
    "&message_origin=https%253A%252F%252Fsr.mihoyo.com"
    "&succ_back_type=message%253Alogin-platform%253Alogin-success"
    "&fail_back_type=message%253Alogin-platform%253Alogin-fail"
    "&ux_mode=popup&iframe_level=1&extra_trace=1#/login/qr"
)
CLOUD_REFERER = "https://sr.mihoyo.com/cloud/"

# ---------------------------------------------------------------------------
# 业务常量
# ---------------------------------------------------------------------------
REQUIRED_COOKIES: tuple[str, ...] = ("cookie_token_v2", "account_mid_v2")
TERMINAL_FAIL_STATUSES: frozenset[str] = frozenset(
    {"Expired", "Failed", "Disabled", "Cancel", "Cancelled"}
)


# ---------------------------------------------------------------------------
# 纯工具函数 —— Dispatcher 等模块可直接 import 复用
# ---------------------------------------------------------------------------
def parse_cookie_header(text: str) -> dict[str, str]:
    """把单行 ``Cookie`` header 拆成 dict, 值会做 URL 解码。"""
    from urllib.parse import unquote_plus

    out: dict[str, str] = {}
    for part in (text or "").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        out[key.strip()] = unquote_plus(value.strip())
    return out


def is_placeholder(value: str) -> bool:
    """check_cookies.py 里的占位符约定: 含 ``*`` 视为打码后的不可用值。"""
    return "*" in value


def gen_device_fp() -> str:
    """生成 13 位十六进制 ``DEVICEFP`` (与浏览器 SDK 字符集/长度一致)。"""
    return secrets.token_hex(7)[:13]


def gen_lifecycle_id() -> str:
    """通行证 SDK 每次启动随机生成的 10 位十六进制 lifecycle id。"""
    return secrets.token_hex(5)


def make_passport_headers(device_id: str, device_fp: str, lifecycle_id: str) -> dict[str, str]:
    """通行证 SDK (createQRLogin / queryQRLoginStatus) 通用请求头。"""
    return {
        "user-agent": USER_AGENT,
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://user.mihoyo.com",
        "referer": PASSPORT_REFERER,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
        "x-rpc-app_id": PASSPORT_APP_ID,
        "x-rpc-client_type": "25",
        "x-rpc-device_id": device_id,
        "x-rpc-device_fp": device_fp,
        "x-rpc-device_model": "Chrome%20149.0.0.0",
        "x-rpc-device_name": "Chrome",
        "x-rpc-device_os": "Linux%2064-bit",
        "x-rpc-game_biz": GAME_BIZ,
        "x-rpc-language": "zh-cn",
        "x-rpc-lifecycle_id": lifecycle_id,
        "x-rpc-mi_referrer": PASSPORT_REFERER,
        "x-rpc-sdk_version": PASSPORT_SDK_VERSION,
    }


def make_verify_headers(base: dict[str, str]) -> dict[str, str]:
    """``webVerifyForGame`` 的请求头 (来源切换到云游戏页, sdk_version 不同)。"""
    headers = dict(base)
    headers.update(
        {
            "origin": "https://sr.mihoyo.com",
            "referer": CLOUD_REFERER,
            "x-rpc-mi_referrer": CLOUD_REFERER,
            "x-rpc-sdk_version": SESSION_SDK_VERSION,
            "x-rpc-app_version": "",
        }
    )
    return headers


# ---------------------------------------------------------------------------
# Authenticator
# ---------------------------------------------------------------------------
class Authenticator:
    """米哈游通行证认证客户端: 扫码登录 + cookie 有效性校验。

    与 :class:`core.dispatcher.Dispatcher` 解耦 —— Dispatcher 永远不会 import
    本类, 只共享本模块顶部的常量与纯工具函数。

    典型用法::

        auth = Authenticator()                  # 默认读 ./credentials.json
        valid, info = auth.check()              # 探活
        if not valid:
            auth.login_qrcode()                 # 扫码并写回 credentials.json

    GUI / CLI 集成时通过 ``on_status`` 回调接管文字进度提示,
    通过 ``terminal=False`` / ``save_png=False`` 控制二维码渲染目的地。
    """

    def __init__(
        self,
        credentials_path: Path | str = "credentials.json",
        *,
        qr_dir: Path | str = "log",
        logger: logging.Logger | None = None,
    ) -> None:
        """初始化认证客户端。

        参数:
            credentials_path: ``credentials.json`` 路径, 同时也是设备指纹的
                来源 —— 若文件存在, ``_MHYUUID`` / ``DEVICEFP`` 等会被复用。
            qr_dir: 扫码时二维码 PNG 的输出目录, 不存在会自动创建。
            logger: 自定义日志器; 默认使用 ``core.log.get_logger("auth")``。
        """
        self.credentials_path = Path(credentials_path)
        self.qr_dir = Path(qr_dir)
        self.logger = logger or get_logger("auth")

    # ------------------------------------------------------------------
    # 凭据 IO
    # ------------------------------------------------------------------
    def load_cookie(self) -> str:
        """从 ``credentials.json`` 读取 ``cookie`` 字段; 文件缺失/字段缺失返回空串。"""
        path = self.credentials_path
        if not path.exists():
            return ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.logger.warning("读取 %s 失败: %s", path, exc)
            return ""
        return str(data.get("cookie") or "")

    def save_cookie(self, cookie: str, *, backup: bool = True) -> Path:
        """把 cookie 写回 ``credentials.json``; 已存在时按时间戳生成 ``.bak``。"""
        path = self.credentials_path
        if path.exists() and backup:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = path.with_suffix(path.suffix + f".bak.{timestamp}")
            backup_path.write_bytes(path.read_bytes())
            self.logger.info("原文件已备份: %s", backup_path)
        payload = {"cookie": cookie}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------
    def check(self, cookie: str | None = None, *, timeout: float = 15.0) -> tuple[bool, dict[str, Any]]:
        """通过 ``webVerifyForGame`` 拉取个人信息, 判断 cookie 是否仍然有效。

        参数:
            cookie: 单行 Cookie header; ``None`` 时自动调用 :meth:`load_cookie`。
            timeout: 单次请求超时秒数。

        返回:
            ``(valid, info)``。``info`` 至少包含 ``retcode``、``message``、
            ``cookies`` (解析后的 dict) 与 ``missing`` (缺失的必需字段列表);
            ``valid=True`` 时还会带 ``aid`` / ``mid`` / ``mobile`` / ``realname`` /
            ``is_adult`` / ``user_info``; ``valid=False`` 且发生网络错误时
            带 ``error``。

        失败路径:
            * 必需字段缺失/占位 —— 不发请求直接返回, ``retcode=-1``。
            * 网络异常 —— ``retcode=-2``, ``error`` 为异常消息。
            * 服务端拒绝 —— ``retcode`` 为服务端 retcode (例如 ``-100`` 表示
              token 失效)。
        """
        if cookie is None:
            cookie = self.load_cookie()
        cookies = parse_cookie_header(cookie)
        info: dict[str, Any] = {"cookies": cookies}

        missing = [
            name for name in REQUIRED_COOKIES
            if not cookies.get(name) or is_placeholder(cookies[name])
        ]
        info["missing"] = missing
        if missing:
            info["retcode"] = -1
            info["message"] = f"缺少必需 Cookie 字段: {missing}"
            info["error"] = info["message"]
            return False, info

        device_id = cookies.get("_MHYUUID") or str(uuid.uuid4())
        device_fp = cookies.get("DEVICEFP") or gen_device_fp()
        lifecycle_id = cookies.get("MIHOYO_LOGIN_PLATFORM_LIFECYCLE_ID") or gen_lifecycle_id()

        headers = make_verify_headers(make_passport_headers(device_id, device_fp, lifecycle_id))
        headers["cookie"] = cookie

        try:
            response = requests.post(WEB_VERIFY_URL, headers=headers, json={}, timeout=timeout)
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            info["retcode"] = -2
            info["message"] = f"请求失败: {exc}"
            info["error"] = str(exc)
            return False, info

        info["retcode"] = payload.get("retcode")
        info["message"] = payload.get("message")
        if payload.get("retcode") != 0:
            return False, info

        user_info = (payload.get("data") or {}).get("user_info") or {}
        info["user_info"] = user_info
        info["aid"] = user_info.get("aid", "")
        info["mid"] = user_info.get("mid", "")
        info["mobile"] = user_info.get("mobile", "")
        info["realname"] = user_info.get("realname", "")
        info["is_adult"] = user_info.get("is_adult", 0)
        return True, info

    # ------------------------------------------------------------------
    # 扫码登录
    # ------------------------------------------------------------------
    def login_qrcode(
        self,
        *,
        poll_interval: float = 3.0,
        timeout: int = 180,
        verify: bool = True,
        write_credentials: bool = True,
        backup: bool = True,
        save_png: bool = True,
        terminal: bool = True,
        light_terminal: bool = False,
        on_status: Callable[[str], None] | None = None,
    ) -> str:
        """完整扫码登录流程, 返回单行 cookie header。

        步骤::

            createQRLogin → 渲染二维码 → 轮询 queryQRLoginStatus
                → (可选) webVerifyForGame → (可选) 写出 credentials.json

        参数:
            poll_interval: 轮询间隔秒, 过短会被服务端判为失效。
            timeout: 等待扫码总超时秒。
            verify: 是否在 ``Confirmed`` 后追加一次 ``webVerifyForGame``,
                与浏览器实际行为一致并刷新 cookie。
            write_credentials: 是否把结果写回 :attr:`credentials_path`。
            backup: 写入前是否生成 ``.bak.<timestamp>`` 备份。
            save_png: 是否在 :attr:`qr_dir` 下保存 PNG 二维码。
            terminal: 是否把二维码渲染到终端 (适合 SSH 场景)。
            light_terminal: 浅色终端时取消反色, 默认按深色终端反色显示。
            on_status: 进度回调, 每个里程碑用一行字符串报告; ``None`` 时
                通过 :attr:`logger` 以 INFO 级别输出。

        返回:
            服务端确认后的单行 ``Cookie`` header (含必需字段); 即使
            ``write_credentials=False`` 也会返回, 由调用方自行处理。

        异常:
            ``RuntimeError``: 二维码失效、轮询超时、服务端非零 retcode 等。
        """
        # qrcode 仅扫码流程需要, 延迟导入避免 dispatcher 链路被动加载 PIL。
        import qrcode

        def report(message: str) -> None:
            if on_status is not None:
                on_status(message)
            else:
                self.logger.info(message)

        bootstrap = self._load_bootstrap()
        device_id = bootstrap["_MHYUUID"]
        device_fp = bootstrap["DEVICEFP"]
        lifecycle_id = bootstrap["MIHOYO_LOGIN_PLATFORM_LIFECYCLE_ID"]

        session = requests.Session()
        for name, value in bootstrap.items():
            session.cookies.set(name, value, domain=".mihoyo.com", path="/")
        headers = make_passport_headers(device_id, device_fp, lifecycle_id)

        # ---- 1) 申请二维码 ----
        report(
            f"[1/4] device_id={device_id}, device_fp={device_fp}, lifecycle_id={lifecycle_id}"
        )
        report("       POST createQRLogin ...")
        qr_resp = self._post_json(session, CREATE_QR_URL, headers, {})
        if qr_resp.get("retcode") != 0:
            raise RuntimeError(f"createQRLogin 失败: {qr_resp}")
        qr_url = qr_resp["data"]["url"]
        ticket = qr_resp["data"]["ticket"]
        report(f"       ticket = {ticket}")
        report(f"       QR url = {qr_url}")

        # ---- 2) 渲染二维码 ----
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.qr_dir.mkdir(parents=True, exist_ok=True)
        qr_path = self.qr_dir / f"qrcode_{timestamp}.png"
        qr = qrcode.QRCode(border=2, box_size=10)
        qr.add_data(qr_url)
        qr.make(fit=True)
        if save_png:
            qr.make_image(fill_color="black", back_color="white").save(qr_path)
            report(f"[2/4] 二维码已保存: {qr_path.resolve()}")
        else:
            report("[2/4] 二维码 (跳过 PNG)")
        if terminal:
            # 深色终端 invert=True 用 █, 浅色终端 light_terminal=True 翻回正色;
            # tty=False 用半块字符 (▀▄), 体积是整块的一半, 多数手机仍可扫。
            print()
            qr.print_ascii(tty=False, invert=not light_terminal)
            print()
        report("       请用「米游社」或 「云·星穹铁道」移动端（推荐）扫码 → 在手机上确认登录")

        # ---- 3) 轮询登录状态 ----
        report(f"[3/4] 开始轮询 (间隔 {poll_interval}s, 超时 {timeout}s) ...")
        user_info = self._poll_status(
            session, headers, ticket,
            poll_interval=poll_interval,
            timeout=timeout,
            report=report,
        )
        aid = user_info.get("aid", "")
        mid = user_info.get("mid", "")
        safe_mobile = user_info.get("mobile", "")
        report(f"       已确认登录: aid={aid}, mid={mid}, mobile={safe_mobile}")

        # ---- 4) 可选: webVerifyForGame ----
        if verify:
            report("[4/4] POST webVerifyForGame ...")
            verify_resp = self._post_json(session, WEB_VERIFY_URL, make_verify_headers(headers), {})
            if verify_resp.get("retcode") != 0:
                report(
                    f"       警告: webVerifyForGame retcode={verify_resp.get('retcode')}"
                    f" message={verify_resp.get('message')}"
                )
            else:
                report("       OK")
        else:
            report("[4/4] 跳过 webVerifyForGame (verify=False)")

        # ---- 整理 cookies ----
        cookies: dict[str, str] = {c.name: c.value for c in session.cookies}
        # 兜底: bootstrap 写入的 _MHYUUID 等可能没被服务端再次 Set-Cookie, 保留下来
        for name, value in bootstrap.items():
            cookies.setdefault(name, value)
        cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())

        if write_credentials:
            saved = self.save_cookie(cookie_header, backup=backup)
            report(f"       已写入: {saved}  (共 {len(cookies)} 个 cookie 字段)")

        return cookie_header

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _load_bootstrap(self) -> dict[str, str]:
        """从已有 credentials.json 复用设备指纹相关字段, 缺失/失效时新生成。"""
        bootstrap: dict[str, str] = {}
        existing = parse_cookie_header(self.load_cookie())
        for key in ("_MHYUUID", "DEVICEFP_SEED_ID", "DEVICEFP_SEED_TIME", "DEVICEFP"):
            value = existing.get(key)
            if value and not is_placeholder(value):
                bootstrap[key] = value

        bootstrap.setdefault("_MHYUUID", str(uuid.uuid4()))
        bootstrap.setdefault("DEVICEFP_SEED_ID", secrets.token_hex(8))
        bootstrap.setdefault("DEVICEFP_SEED_TIME", str(int(time.time() * 1000)))
        bootstrap.setdefault("DEVICEFP", gen_device_fp())
        bootstrap["mi18nLang"] = "zh-cn"
        bootstrap["MIHOYO_LOGIN_PLATFORM_LIFECYCLE_ID"] = gen_lifecycle_id()
        return bootstrap

    @staticmethod
    def _post_json(
        session: requests.Session,
        url: str,
        headers: dict[str, str],
        body: dict,
    ) -> dict[str, Any]:
        """带详细错误信息的 JSON POST。"""
        response = session.post(url, headers=headers, json=body, timeout=20)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"{url} 返回非 JSON HTTP {response.status_code}: {response.text[:200]}"
            ) from exc
        if response.status_code >= 300:
            raise RuntimeError(f"{url} HTTP {response.status_code}: {payload}")
        return payload

    @classmethod
    def _poll_status(
        cls,
        session: requests.Session,
        headers: dict[str, str],
        ticket: str,
        *,
        poll_interval: float,
        timeout: int,
        report: Callable[[str], None],
    ) -> dict[str, Any]:
        """轮询 queryQRLoginStatus 直到 ``Confirmed`` 或终态/超时。"""
        deadline = time.monotonic() + max(timeout, 1)
        last_status: str | None = None
        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError("等待扫码超时, 请重新运行")
            status_resp = cls._post_json(session, QUERY_QR_URL, headers, {"ticket": ticket})
            if status_resp.get("retcode") != 0:
                raise RuntimeError(f"queryQRLoginStatus 失败: {status_resp}")
            data = status_resp["data"]
            status = data.get("status") or ""
            if status != last_status:
                report(f"       status: {status}")
                last_status = status
            if status == "Confirmed":
                return data.get("user_info") or {}
            if status in TERMINAL_FAIL_STATUSES:
                raise RuntimeError(f"二维码已失效: status={status}")
            time.sleep(poll_interval)


__all__ = [
    "Authenticator",
    "CLOUD_REFERER",
    "CREATE_QR_URL",
    "GAME_BIZ",
    "PASSPORT_APP_ID",
    "PASSPORT_BASE",
    "PASSPORT_REFERER",
    "PASSPORT_SDK_VERSION",
    "QUERY_QR_URL",
    "REQUIRED_COOKIES",
    "SEC_CH_UA",
    "SESSION_SDK_VERSION",
    "TERMINAL_FAIL_STATUSES",
    "USER_AGENT",
    "WEB_VERIFY_URL",
    "gen_device_fp",
    "gen_lifecycle_id",
    "is_placeholder",
    "make_passport_headers",
    "make_verify_headers",
    "parse_cookie_header",
]
