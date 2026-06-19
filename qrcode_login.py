"""米哈游通行证扫码登录 / cookie 校验的命令行入口。

业务逻辑全部位于 :mod:`core.auth.Authenticator`; 本脚本只负责命令行参数
解析、文件 IO 和人类可读输出。

抓包参考: ``log/qrcode_login.har``。完整流程与端点在 :mod:`core.auth`
模块文档中说明。

CLI 子命令::

    python qrcode_login.py login   # 默认: 扫码登录, 写 credentials.json
    python qrcode_login.py check   # 用 credentials.json 当前 cookie 验证有效性
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.auth import (
    REQUIRED_COOKIES,
    Authenticator,
    is_placeholder,
    load_cookie,
    parse_cookie_header,
    save_cookie,
)


def report_cookies(cookies: dict[str, str]) -> int:
    """简化版 check_cookies, 只关注必需字段, 返回缺失数量。"""
    missing: list[str] = []
    print("\n关键 Cookie 字段:")
    for name in REQUIRED_COOKIES:
        value = cookies.get(name) or ""
        usable = bool(value) and not is_placeholder(value)
        status = "存在" if usable else ("占位" if value else "缺失")
        if not usable:
            missing.append(name)
        preview = value[:6] + "..." + value[-4:] if len(value) > 12 else "*" * len(value)
        print(f"  [{status}] {name:<20} 长度={len(value):<4} {preview}")
    return len(missing)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="米哈游通行证扫码登录 / cookie 有效性校验")
    sub = parser.add_subparsers(dest="command")

    p_login = sub.add_parser("login", help="扫码登录, 写出 credentials.json (默认子命令)")
    p_login.add_argument("--output", default="credentials.json", help="结果写入路径 (默认 credentials.json)")
    p_login.add_argument(
        "--credentials",
        default=None,
        help="读取 _MHYUUID / DEVICEFP 等设备指纹的来源 (默认与 --output 相同)",
    )
    p_login.add_argument("--qr-dir", default="log", help="二维码图片保存目录 (默认 log)")
    p_login.add_argument("--poll-interval", type=float, default=3.0, help="轮询间隔秒 (默认 3, 过短会被服务器判为失效)")
    p_login.add_argument("--timeout", type=int, default=180, help="等待扫码总超时秒 (默认 180)")
    p_login.add_argument(
        "--no-verify",
        action="store_true",
        help="跳过 webVerifyForGame (仅靠 queryQRLoginStatus 返回的 Cookie 也已满足 check_cookies)",
    )
    p_login.add_argument(
        "--no-backup",
        action="store_true",
        help="覆盖输出文件时不创建 .bak 备份",
    )
    p_login.add_argument(
        "--no-terminal",
        action="store_true",
        help="不把二维码打印到终端 (默认会打印, 方便直接扫)",
    )
    p_login.add_argument(
        "--no-png",
        action="store_true",
        help="不保存 PNG 文件 (只打到终端)",
    )
    p_login.add_argument(
        "--light-terminal",
        action="store_true",
        help="浅色终端用 (默认按深色终端反色打印, 浅色加这个开关把颜色再翻回来)",
    )

    p_check = sub.add_parser("check", help="用 webVerifyForGame 校验 cookie 是否仍然有效")
    p_check.add_argument(
        "credentials",
        nargs="?",
        default="credentials.json",
        help="credentials.json 路径 (默认 credentials.json)",
    )
    p_check.add_argument("--cookie", help="直接传单行 Cookie 字符串, 优先级高于 credentials 文件")
    p_check.add_argument("--json", action="store_true", help="结果以 JSON 输出, 便于脚本调用")

    args = parser.parse_args()
    if args.command is None:
        # 不带子命令时维持旧行为: 直接 login
        args = parser.parse_args(["login", *sys.argv[1:]])
    return args


def cmd_check(args: argparse.Namespace) -> int:
    """``check`` 子命令: 调 ``Authenticator.check`` 并友好打印结果。"""
    auth = Authenticator()
    cookie = args.cookie
    if cookie is None:
        cookie = load_cookie(args.credentials)
    valid, info = auth.check(cookie)

    if args.json:
        # 不打印原始 cookies 细节, 避免误把 token 落盘到日志
        report = {k: v for k, v in info.items() if k != "cookies"}
        report["valid"] = valid
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if valid else 1

    if valid:
        print("[有效]  webVerifyForGame OK")
        print(f"  aid      = {info.get('aid')}")
        print(f"  mid      = {info.get('mid')}")
        print(f"  mobile   = {info.get('mobile')}")
        print(f"  realname = {info.get('realname')}")
        print(f"  is_adult = {info.get('is_adult')}")
        return 0

    print("[失效]")
    if info.get("missing"):
        print(f"  缺少必需 Cookie: {info['missing']}")
    print(f"  retcode = {info.get('retcode')}")
    print(f"  message = {info.get('message')}")
    if info.get("error"):
        print(f"  error   = {info['error']}")
    return 1


def cmd_login(args: argparse.Namespace) -> int:
    """``login`` 子命令: 走完扫码流程, 末尾打印必需字段报告。"""
    # 设备指纹的来源默认与输出文件相同, 便于复用 _MHYUUID / DEVICEFP
    bootstrap_path = Path(args.credentials) if args.credentials else Path(args.output)
    output_path = Path(args.output)

    auth = Authenticator(qr_dir=args.qr_dir)
    cookie = auth.login_qrcode(
        existing_cookie=load_cookie(bootstrap_path),
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        verify=not args.no_verify,
        save_png=not args.no_png,
        terminal=not args.no_terminal,
        light_terminal=args.light_terminal,
        on_status=print,
    )

    saved = save_cookie(output_path, cookie, backup=not args.no_backup)
    cookies = parse_cookie_header(cookie)
    print(f"      已写入: {saved}  (共 {len(cookies)} 个 cookie 字段)")

    missing = report_cookies(cookies)
    if missing:
        print(f"\n失败: 仍有 {missing} 个必需字段缺失")
        return 1
    print("\n成功: 必需字段齐全, 可直接用于 demo.py / ui.py")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "check":
        return cmd_check(args)
    return cmd_login(args)


if __name__ == "__main__":
    sys.exit(main())
