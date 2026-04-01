import re
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_PERIODS = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"}


def parse_set_filename(filename: str) -> Optional[dict]:
    """
    從 .set 檔名解析回測參數。
    格式：{EA名稱}-{幣對}-{週期}-{起始日}-{結束日}-{版本}.set
    例如：SRM_v6.0_AlgoX_REAL-EURUSD-H1-20260201-20260312-v1.set

    回傳 dict: expert, symbol, period, from_date, to_date
    解析失敗回傳 None
    """
    stem = Path(filename).stem  # 去掉 .set
    parts = stem.split("-")

    if len(parts) < 6:
        logger.warning(f"檔名格式不符（段數不足）：{filename}")
        return None

    # 從右往左取：版本(skip), 結束日, 起始日, 週期, 幣對, 剩餘=EA名稱
    version = parts[-1]       # noqa: F841
    to_date_raw = parts[-2]
    from_date_raw = parts[-3]
    period = parts[-4]
    symbol = parts[-5]
    expert_name = "-".join(parts[:-5])

    # 驗證
    if not re.match(r"^\d{8}$", from_date_raw):
        logger.warning(f"起始日格式錯誤：{from_date_raw}（檔名：{filename}）")
        return None
    if not re.match(r"^\d{8}$", to_date_raw):
        logger.warning(f"結束日格式錯誤：{to_date_raw}（檔名：{filename}）")
        return None
    if period not in VALID_PERIODS:
        logger.warning(f"週期格式錯誤：{period}（檔名：{filename}）")
        return None
    if not re.match(r"^[A-Z]{6,}$", symbol):
        logger.warning(f"幣對格式錯誤：{symbol}（檔名：{filename}）")
        return None
    if not expert_name:
        logger.warning(f"無法解析 EA 名稱（檔名：{filename}）")
        return None

    # 日期轉換：20260201 → 2026.02.01
    from_date = f"{from_date_raw[:4]}.{from_date_raw[4:6]}.{from_date_raw[6:]}"
    to_date = f"{to_date_raw[:4]}.{to_date_raw[4:6]}.{to_date_raw[6:]}"

    return {
        "expert": f"{expert_name}.ex4",
        "symbol": symbol,
        "period": period,
        "from_date": from_date,
        "to_date": to_date,
    }


def parse_set_file(set_file_path: str) -> dict:
    """
    解析 MT4 .set 檔案，提取參數名稱與值。
    只取不含逗號的行（主值行），忽略 ,F / ,1 / ,2 / ,3 後綴行。
    """
    params = {}

    # 嘗試 UTF-8，失敗則用 CP1252
    for encoding in ("utf-8", "cp1252"):
        try:
            with open(set_file_path, "r", encoding=encoding) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"無法讀取 .set 檔案（編碼問題）：{set_file_path}")

    for line in lines:
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # 跳過帶逗號的輔助行（如 TakeProfit,F=0）
        if "," in key:
            continue
        params[key] = value

    return params


def discover_set_files(settings_dir: str) -> list:
    """掃描目錄下所有 .set 檔案，依檔名排序回傳"""
    dir_path = Path(settings_dir)
    if not dir_path.exists():
        return []
    return sorted(dir_path.glob("*.set"), key=lambda p: p.name)
