import re
import logging
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    set_filename: str
    expert: str
    symbol: str
    period: str
    date_range: str
    deposit: float
    total_net_profit: float
    profit_factor: float
    maximal_drawdown: float
    maximal_drawdown_pct: float
    total_trades: int
    win_rate: float
    expected_payoff: float
    modeling_quality: str
    report_path: str


def parse_number(text: str) -> float:
    """從文字中提取數值"""
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(" ", ""))
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def parse_drawdown_value(text: str) -> float:
    """從 '456.78 (4.57%)' 提取金額"""
    match = re.match(r"([\d.\-\s]+)", text)
    return float(match.group(1).replace(" ", "")) if match else 0.0


def parse_drawdown_pct(text: str) -> float:
    """從 '456.78 (4.57%)' 提取百分比"""
    match = re.search(r"\(([\d.]+)%\)", text)
    return float(match.group(1)) if match else 0.0


def parse_win_rate(metrics: dict) -> float:
    """從 'Profit trades (% of total)' 提取勝率"""
    text = metrics.get("Profit trades (% of total)", "")
    match = re.search(r"\(([\d.]+)%\)", text)
    if match:
        return float(match.group(1))
    # 備用：直接從數值解析
    text2 = metrics.get("Profit trades", "")
    match2 = re.search(r"\(([\d.]+)%\)", text2)
    return float(match2.group(1)) if match2 else 0.0


def parse_report(htm_path: str, set_filename: str, config, bt_config=None) -> Optional[BacktestResult]:
    """解析 MT4 回測報告 HTML，提取績效指標。bt_config 為檔名解析後的回測設定。"""
    if bt_config is None:
        bt_config = config.backtest
    try:
        with open(htm_path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
    except FileNotFoundError:
        logger.error(f"報告檔案不存在：{htm_path}")
        return None

    soup = BeautifulSoup(html, "lxml")

    tables = soup.find_all("table")
    if not tables:
        logger.error(f"報告中找不到表格：{htm_path}")
        return None

    # 建立 label -> value 映射（從第一個表格，即績效摘要）
    # MT4 報告用 colspan 影響 cell 對齊，需展開 colspan 來正確配對
    metrics = {}
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            # 展開 colspan，讓 key-value 配對正確
            texts = []
            for c in cells:
                colspan = int(c.get("colspan", 1))
                text = c.get_text(strip=True)
                texts.append(text)
                # colspan > 1 的 cell 會佔多格，補空字串
                for _ in range(colspan - 1):
                    texts.append("")
            # 每兩個一組配對 key-value
            for i in range(0, len(texts) - 1, 2):
                key = texts[i]
                value = texts[i + 1]
                if key:
                    metrics[key] = value

    if not metrics:
        logger.error(f"無法從報告中提取指標：{htm_path}")
        return None

    logger.debug(f"提取到的指標 keys：{list(metrics.keys())}")

    return BacktestResult(
        set_filename=set_filename,
        expert=bt_config.expert,
        symbol=bt_config.symbol,
        period=bt_config.period,
        date_range=f"{bt_config.from_date} ~ {bt_config.to_date}",
        deposit=bt_config.deposit,
        total_net_profit=parse_number(metrics.get("Total net profit", "0")),
        profit_factor=parse_number(metrics.get("Profit factor", "0")),
        maximal_drawdown=parse_drawdown_value(metrics.get("Maximal drawdown", "0")),
        maximal_drawdown_pct=parse_drawdown_pct(metrics.get("Maximal drawdown", "0")),
        total_trades=int(parse_number(metrics.get("Total trades", "0"))),
        win_rate=parse_win_rate(metrics),
        expected_payoff=parse_number(metrics.get("Expected payoff", "0")),
        modeling_quality=metrics.get("Modelling quality", "N/A"),
        report_path=htm_path,
    )
