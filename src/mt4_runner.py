import subprocess
import os
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def kill_mt4() -> None:
    """強制關閉所有 MT4 terminal.exe 程序"""
    os.system("taskkill /f /im terminal.exe >nul 2>&1")
    time.sleep(3)


def wait_for_report_file(
    htm_path: Path,
    *,
    timeout: float = 120.0,
    poll: float = 0.5,
    min_bytes: int = 64,
    stable_reads: int = 2,
) -> bool:
    """
    MT4 在 TestShutdownTerminal=true 時可能先結束 process，報告 .htm 稍後才寫完。
    輪詢直到檔案存在、非空、且大小短時間內穩定，避免主流程立刻 exists() 失敗。
    """
    deadline = time.monotonic() + timeout
    last_size = -1
    same_count = 0

    while time.monotonic() < deadline:
        try:
            if htm_path.is_file():
                size = htm_path.stat().st_size
                if size >= min_bytes and size == last_size:
                    same_count += 1
                    if same_count >= stable_reads:
                        return True
                else:
                    same_count = 0
                last_size = size
        except OSError:
            last_size = -1
            same_count = 0
        time.sleep(poll)

    try:
        return htm_path.is_file() and htm_path.stat().st_size >= min_bytes
    except OSError:
        return False


def run_backtest(
    terminal_path: str,
    ini_path: str,
    timeout: int = 300,
    kill_before: bool = True,
) -> bool:
    """
    執行單次 MT4 回測。
    流程：關閉 MT4 → 啟動 terminal.exe /config:ini → 等待完成。
    回傳 True=成功，False=超時或錯誤。
    """
    if kill_before:
        logger.info("關閉已開啟的 MT4...")
        kill_mt4()

    if not os.path.exists(terminal_path):
        logger.error(f"找不到 MT4：{terminal_path}")
        return False

    if not os.path.exists(ini_path):
        logger.error(f"找不到設定檔：{ini_path}")
        return False

    logger.info(f"啟動 MT4 回測... 設定檔：{ini_path}")
    # MT4 直接傳 ini 路徑（不用 /config: 前綴）
    cmd = f'"{terminal_path}" "{ini_path}"'
    logger.info(f"執行命令：{cmd}")
    process = subprocess.Popen(cmd, shell=True)

    try:
        process.wait(timeout=timeout)
        rc = process.returncode
        if rc not in (0, None):
            logger.warning(f"MT4 程序結束碼：{rc}（非 0 時回測可能已失敗）")
        else:
            logger.info("回測完成，MT4 已自動關閉")
        return True
    except subprocess.TimeoutExpired:
        logger.warning(f"回測超時（{timeout}秒），強制結束 MT4")
        try:
            process.kill()
        except OSError:
            pass
        # Windows 下 shell=True 時 kill 子程序未必關掉 terminal.exe，統一再強殺
        kill_mt4()
        return False


def verify_report(report_path: str) -> bool:
    """驗證報告檔案是否存在（MT4 會自動加 .htm 副檔名）"""
    htm_path = report_path if report_path.endswith(".htm") else report_path + ".htm"
    exists = os.path.exists(htm_path)
    if exists:
        logger.info(f"報告已產生：{htm_path}")
    else:
        logger.warning(f"報告未產生：{htm_path}")
    return exists
