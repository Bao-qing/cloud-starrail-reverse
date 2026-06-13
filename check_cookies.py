from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import unquote_plus


REQUIRED_COOKIES = [
    "cookie_token_v2",
    "account_mid_v2",
]

OPTIONAL_COOKIES = [
    "_MHYUUID",
    "DEVICEFP_SEED_ID",
    "DEVICEFP_SEED_TIME",
    "DEVICEFP",
    "aliyungf_tc",
    "MIHOYO_LOGIN_PLATFORM_LIFECYCLE_ID",
    "uni_web_token",
    "account_id_v2",
    "ltoken_v2",
    "ltmid_v2",
    "ltuid_v2",
    "cookie_token",
    "account_id",
    "ltoken",
    "ltuid",
    "MIHOYO_LOGIN_PLATFORM_COMMON_TRACE_INFO",
]


def parse_cookie_header(cookie: str) -> dict[str, str]:
    """Parse a Cookie header string into key/value pairs."""
    cookies: dict[str, str] = {}
    for part in cookie.split(";"):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            cookies[item] = ""
            continue
        key, value = item.split("=", 1)
        cookies[key.strip()] = unquote_plus(value.strip())
    return cookies


def mask_value(value: str) -> str:
    """Return a short non-sensitive preview for diagnostics."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def is_placeholder(value: str) -> bool:
    """Return whether a value still looks like the masked example placeholder."""
    return "*" in value


def load_cookie(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    cookie = str(data.get("cookie") or "")
    if not cookie:
        raise RuntimeError(f"missing cookie in {path}")
    return cookie


def print_group(title: str, names: list[str], cookies: dict[str, str]) -> int:
    print(title)
    missing = 0
    for name in names:
        value = cookies.get(name)
        present = bool(value)
        placeholder = bool(value) and is_placeholder(value)
        usable = present and not placeholder
        if not usable:
            missing += 1
        if not present:
            status = "缺失"
        elif placeholder:
            status = "占位"
        else:
            status = "存在"
        length = len(value or "")
        preview = mask_value(value or "")
        print(f"  [{status}] {name:<42} 长度={length:<4} {preview}")
    return missing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 credentials.json 中的 miHoYo 云游戏关键 Cookie 字段。")
    parser.add_argument("path", nargs="?", default="credentials.json", help="credentials.json 路径")
    parser.add_argument("--list-extra", action="store_true", help="列出未纳入检查的额外 Cookie 名")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.path)
    cookie = load_cookie(path)
    cookies = parse_cookie_header(cookie)

    print(f"已读取: {path}")
    print(f"Cookie 字段数量: {len(cookies)}")
    required_missing = print_group("\n云崩铁登录/调度最低必需字段:", REQUIRED_COOKIES, cookies)
    print_group("\n可选 / 兼容字段:", OPTIONAL_COOKIES, cookies)

    if args.list_extra:
        known = set(REQUIRED_COOKIES) | set(OPTIONAL_COOKIES)
        extra = sorted(name for name in cookies if name not in known)
        print("\n额外字段:")
        for name in extra:
            print(f"  {name}")

    if required_missing:
        print(f"\n检查结果: 不可用，缺少或仍为占位值的最低必需 Cookie 字段共 {required_missing} 个。")
        print("建议: 至少提供 cookie_token_v2 和 account_mid_v2；脱敏示例不能直接使用。")
        return 1

    print("\n检查结果: 看起来字段齐全。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
