"""
自动化流程演示
"""
import asyncio
import contextlib
import logging
import time
from pathlib import Path

from core import CloudGame, QUEUE_TYPE_COIN, QUEUE_TYPE_NORMAL, configure_logging, get_logger
from core.models import CloudGameConfig


logger = get_logger("demo")


# def load_core_config(path: Path = Path("client_profile.json")) -> dict | None:
#     if not path.exists():
#         return None
#     try:
#         return loads_json_with_comments(path.read_text(encoding="utf-8"))
#     except ValueError as exc:
#         raise RuntimeError(f"core config must be a JSON object: {path}") from exc


def authenticate(cloud_game: CloudGame) -> None:
    """所有 demo 在 dispatch / connect 前的统一前置: 检查或登录。

    ``ensure_login(auto_login=True)`` 会:
        1. 从 ``credentials.json`` 加载 cookie;
        2. 调 ``webVerifyForGame`` 探活;
        3. 失效或缺失时, 自动启动扫码登录 (在终端打印二维码 + 写出
           ``log/qrcode_<时间戳>.png``), 完成后写回 ``credentials.json``。

    若 demo 跑在没有终端交互的环境 (CI / 容器), 改成 ``auto_login=False`` 让
    它在 cookie 失效时直接抛 ``RuntimeError`` 即可, 由调用方决定如何引导。
    """
    info = cloud_game.ensure_login(auto_login=True)
    logger.info("登录态有效, cookie 长度=%s", len(info.cookie))


async def snapshot_interval() -> None:
    config = CloudGameConfig(
        max_seconds=0,
        queue_type=queue_type,
        # core_config=load_core_config(),
        snapshot_interval=5,
        snapshot_dir=".",
    )
    cloud_game = CloudGame(
        config=config,
        # callbacks=CloudGameCallbacks(
        #     on_status=lambda message, level: logger.log(level, message),
        #     on_dispatch_log=lambda message, level: logger.log(level, message),
        # ),
    )
    authenticate(cloud_game)
    await cloud_game.run(dispatch=True, connect=True)

async def snapshot_manual() -> None:
    config = CloudGameConfig(
        max_seconds=0,
        queue_type=queue_type,
        # core_config=load_core_config(),
        # snapshot_interval=5,
        # snapshot_dir=".",
    )
    cloud_game = CloudGame(
        config=config,
        # callbacks=CloudGameCallbacks(
        #     on_status=lambda message, level: logger.log(level, message),
        #     on_dispatch_log=lambda message, level: logger.log(level, message),
        # ),
    )
    authenticate(cloud_game)
    run_task = asyncio.create_task(cloud_game.run(dispatch=True, connect=True))
    try:
        while cloud_game.game_session is None:
            if run_task.done():
                await run_task
            await asyncio.sleep(0.1)
        while True:
            result = await cloud_game.capture_video_frame(timeout=5.0)
            if result is None:
                logger.warning("video frame capture timed out")
                continue
            image, count = result
            path = Path(f"manual_frame_{int(time.time())}_f{count:06d}.jpg")
            image.save(path, "JPEG", quality=90)
            logger.info("saved frame: %s", path)
            await asyncio.sleep(5.0)
    finally:
        run_task.cancel()


async def account_info() -> None:
    configure_logging(logging.INFO, log_file="demo.log")
    config = CloudGameConfig(
        queue_type=queue_type,
        # core_config=load_core_config(),
    )
    cloud_game = CloudGame(
        config=config,
    )
    authenticate(cloud_game)

    wallet = await asyncio.to_thread(cloud_game.get_wallet_info)
    summary = wallet.get("summary") or {}
    logger.info(
        "剩余时长: 星云币=%s 个(约 %s 分钟), 免费=%s 分钟, 畅玩卡=%s 秒",
        summary.get("coin_num"),
        summary.get("coin_minutes"),
        summary.get("free_time_minutes"),
        summary.get("play_card_remaining_sec"),
    )

    queue_estimate = await asyncio.to_thread(cloud_game.get_queue_estimate)
    normal = queue_estimate.get("normal") or {}
    coin = queue_estimate.get("coin") or {}
    node = queue_estimate.get("node") or {}
    logger.info(
        "预计排队: 节点=%s, 普通队列=%s 人/约 %s 分钟, 星云币队列=%s 人/约 %s 分钟",
        node.get("node_name") or node.get("node_id"),
        normal.get("queue_len") or normal.get("queue_length"),
        normal.get("waiting_time_min"),
        coin.get("queue_len") or coin.get("queue_length"),
        coin.get("waiting_time_min"),
    )


async def input_demo() -> None:
    config = CloudGameConfig(
        max_seconds=0,
        queue_type=queue_type,
        video_frame_interval=None,
        # core_config=load_core_config(),
    )
    cloud_game = CloudGame(
        config=config,
    )
    authenticate(cloud_game)

    async def save_screenshot(filename: str, label: str) -> None:
        result = await cloud_game.capture_video_frame(timeout=8.0)
        if result is None:
            logger.warning("截图失败: %s (%s)", label, filename)
            return
        image, count = result
        path = Path(filename)
        image.save(path, "JPEG", quality=90)
        logger.info("截图: %s -> %s (frame %s)", label, path, count)

    async def click_center() -> None:
        x = 0.5
        y = 0.5
        cloud_game.send_input({"type": "move", "x": x, "y": y, "dx": 0.0, "dy": 0.0})
        cloud_game.send_input({"type": "down", "button": "left", "x": x, "y": y})
        await asyncio.sleep(0.08)
        cloud_game.send_input({"type": "up", "button": "left", "x": x, "y": y})

    async def press_key(key_code: int, label: str) -> None:
        cloud_game.send_input({"type": "key_down", "key_code": key_code, "capslock": False, "numlock": False})
        await asyncio.sleep(0.05)
        cloud_game.send_input({"type": "key_up", "key_code": key_code, "capslock": False, "numlock": False})
        logger.info("输入按键: %s (code %s)", label, key_code)

    run_task = asyncio.create_task(cloud_game.run(dispatch=True, connect=True))
    try:
        logger.info("等待会话启动...")
        while cloud_game.game_session is None:
            if run_task.done():
                await run_task
            await asyncio.sleep(0.1)

        logger.info("等待视频首帧...")
        connected = await cloud_game.game_session.wait_for_video_connected()
        if not connected:
            return False

        logger.info("等待 30s 后截取进入游戏前画面...")
        await asyncio.sleep(30)
        await save_screenshot("input_demo_01_before_enter.jpg", "进入游戏前画面")

        logger.info("连续点击屏幕中心 10s，间隔 1s...")
        for index in range(10):
            await click_center()
            logger.info("中心点击 %s/10", index + 1)
            await asyncio.sleep(1)

        logger.info("等待 5s 后截取游戏主界面...")
        await asyncio.sleep(5)
        await save_screenshot("input_demo_02_main_screen.jpg", "游戏主界面")

        await press_key(ord("B"), "B 打开背包")
        await asyncio.sleep(2)
        await save_screenshot("input_demo_03_bag.jpg", "背包界面")

        await press_key(27, "Esc 退出背包")
        await asyncio.sleep(1)
        await press_key(27, "Esc 打开菜单")
        await asyncio.sleep(3)
        await save_screenshot("input_demo_04_menu.jpg", "菜单界面")
    finally:
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


async def redeem_code_demo() -> None:
    # configure_logging(logging.DEBUG, log_file="demo.log")
    config = CloudGameConfig(
        max_seconds=0,
        queue_type=queue_type,
        video_frame_interval=None,
        # core_config=load_core_config(),
    )
    cloud_game = CloudGame(
        config=config,
    )
    authenticate(cloud_game)

    async def save_screenshot(filename: str, label: str) -> None:
        result = await cloud_game.capture_video_frame(timeout=8.0)
        if result is None:
            logger.warning("截图失败: %s (%s)", label, filename)
            return
        image, count = result
        path = Path(filename)
        image.save(path, "JPEG", quality=90)
        logger.info("截图: %s -> %s (frame %s)", label, path, count)

    async def wait_and_screenshot(filename: str, label: str, delay: float = 5.0) -> None:
        logger.info("等待 %.1fs 后截图: %s -> %s", delay, label, filename)
        await asyncio.sleep(delay)
        await save_screenshot(filename, label)

    async def click_at(x: float, y: float, label: str) -> None:
        cloud_game.send_input({"type": "move", "x": x, "y": y, "dx": 0.0, "dy": 0.0})
        cloud_game.send_input({"type": "down", "button": "left", "x": x, "y": y})
        await asyncio.sleep(0.08)
        cloud_game.send_input({"type": "up", "button": "left", "x": x, "y": y})
        logger.info("点击: %s x=%.4f y=%.4f", label, x, y)

    async def press_key(key_code: int, label: str) -> None:
        cloud_game.send_input({"type": "key_down", "key_code": key_code, "capslock": False, "numlock": False})
        await asyncio.sleep(0.05)
        cloud_game.send_input({"type": "key_up", "key_code": key_code, "capslock": False, "numlock": False})
        logger.info("输入按键: %s (code %s)", label, key_code)

    async def inject_text(text: str, label: str) -> None:
        cloud_game.send_input({"type": "ime", "text": text})
        logger.info("注入文本: %s (%s)", label, text)

    run_task = asyncio.create_task(cloud_game.run(dispatch=True, connect=True))
    try:
        logger.info("等待会话启动...")
        while cloud_game.game_session is None:
            if run_task.done():
                await run_task
            await asyncio.sleep(0.1)

        logger.info("等待视频首帧...")
        connected = await cloud_game.game_session.wait_for_video_connected()
        if not connected:
            return False

        logger.info("等待 30s 后截取进入游戏前画面...")
        await asyncio.sleep(30)
        await save_screenshot("redeem_demo_01_before_enter.jpg", "进入游戏前画面")

        logger.info("连续点击屏幕中心 10s，间隔 1s，确保进入游戏...")
        for index in range(10):
            await click_at(0.5, 0.5, f"中心点击 {index + 1}/10")
            await asyncio.sleep(1)

        await wait_and_screenshot("redeem_demo_02_main_screen.jpg", "游戏主界面")

        await press_key(27, "Esc 打开菜单")
        await wait_and_screenshot("redeem_demo_03_menu_open.jpg", "打开菜单")

        await click_at(0.9127, 0.0950, "菜单右上入口")
        await wait_and_screenshot("redeem_demo_04_after_click_09127_00950.jpg", "点击 0.9127 0.0950 后")

        await click_at(0.8396, 0.3252, "兑换码入口")
        await wait_and_screenshot("redeem_demo_05_after_click_08396_03252.jpg", "点击 0.8396 0.3252 后")

        await click_at(0.3072, 0.4889, "兑换码输入框")
        await wait_and_screenshot("redeem_demo_06_code_input_focused.jpg", "点击 0.3072 0.4889 后")

        await inject_text("sr8888", "兑换码")
        await wait_and_screenshot("redeem_demo_07_code_text.jpg", "注入文本 sr888 后")

        await click_at(0.5954, 0.6610, "确认兑换")
        await wait_and_screenshot("redeem_demo_08_submit.jpg", "点击 0.5954 0.6610 后")
    finally:
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task


if __name__ == "__main__":
    configure_logging(logging.INFO, log_file="demo.log")
    queue_type =  QUEUE_TYPE_NORMAL # QUEUE_TYPE_NORMAL / QUEUE_TYPE_COIN
    # input("demo使用完全硬编码流程，可能出现意想不到的问题，请知晓风险，回车继续执行...")
    ## ------------------------------
    # 查询剩余时长和预计排队时长
    # asyncio.run(account_info())

    ## ------------------------------
    # 自动输出快照
    # asyncio.run(snapshot_interval())

    ## ------------------------------
    # 手动截图
    # asyncio.run(snapshot_manual())

    ## ------------------------------
    # 输入演示：等待进入画面、点击中心、打开背包和菜单并截图
    # asyncio.run(input_demo())

    ## ------------------------------
    # 兑换码使用演示：进入游戏、打开菜单、输入兑换码并逐步截图
    asyncio.run(redeem_code_demo())
