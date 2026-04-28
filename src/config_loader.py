import yaml
from pathlib import Path
from dataclasses import dataclass


@dataclass
class MT4Config:
    terminal_path: str
    data_dir: str


@dataclass
class BacktestConfig:
    expert: str
    symbol: str
    period: str
    model: int
    spread: int
    from_date: str
    to_date: str
    deposit: int
    currency: str
    leverage: int


@dataclass
class PathsConfig:
    settings_dir: Path
    results_dir: Path
    reports_dir: Path
    excel_path: Path


@dataclass
class RunnerConfig:
    timeout: int
    cooldown: int
    kill_before_run: bool
    # MT4 關閉後，報告 .htm 可能延遲寫入磁碟；輪詢等待避免偶發「找不到報告」
    report_wait_timeout: int
    report_poll_interval: float
    max_retries: int  # 報告未產生時最多重試次數


@dataclass
class AppConfig:
    mt4: MT4Config
    backtest: BacktestConfig
    paths: PathsConfig
    runner: RunnerConfig
    symbol_map: dict[str, str]


def load_config(config_path: str) -> AppConfig:
    """載入 config.yaml 並回傳結構化的 AppConfig"""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"找不到設定檔：{config_path}")

    with open(config_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    base_dir = config_file.parent

    # 解析路徑（相對路徑以 config.yaml 所在目錄為基準）
    settings_dir = base_dir / raw["paths"]["settings_dir"]
    results_dir = base_dir / raw["paths"]["results_dir"]
    reports_dir = results_dir / raw["paths"]["reports_subdir"]
    excel_path = results_dir / raw["paths"]["excel_filename"]

    mt4 = MT4Config(
        terminal_path=raw["mt4"]["terminal_path"],
        data_dir=raw["mt4"]["data_dir"],
    )

    backtest = BacktestConfig(
        expert=raw["backtest"]["expert"],
        symbol=raw["backtest"]["symbol"],
        period=raw["backtest"]["period"],
        model=raw["backtest"]["model"],
        spread=int(raw["backtest"].get("spread", 0)),
        from_date=raw["backtest"]["from_date"],
        to_date=raw["backtest"]["to_date"],
        deposit=raw["backtest"]["deposit"],
        currency=raw["backtest"]["currency"],
        leverage=raw["backtest"]["leverage"],
    )

    paths = PathsConfig(
        settings_dir=settings_dir,
        results_dir=results_dir,
        reports_dir=reports_dir,
        excel_path=excel_path,
    )

    r = raw["runner"]
    runner = RunnerConfig(
        timeout=r["timeout"],
        cooldown=r["cooldown"],
        kill_before_run=r["kill_before_run"],
        report_wait_timeout=int(r.get("report_wait_timeout", 120)),
        report_poll_interval=float(r.get("report_poll_interval", 0.5)),
        max_retries=int(r.get("max_retries", 1)),
    )

    symbol_map = raw.get("symbol_map", {}) or {}
    if not isinstance(symbol_map, dict):
        raise ValueError("config.yaml 的 symbol_map 必須是 key/value 的對照表（dict）")

    # 驗證 MT4 路徑
    if not Path(mt4.terminal_path).exists():
        raise FileNotFoundError(f"找不到 MT4 terminal：{mt4.terminal_path}")

    return AppConfig(mt4=mt4, backtest=backtest, paths=paths, runner=runner, symbol_map=symbol_map)
