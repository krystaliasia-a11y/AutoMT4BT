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


@dataclass
class AppConfig:
    mt4: MT4Config
    backtest: BacktestConfig
    paths: PathsConfig
    runner: RunnerConfig


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

    runner = RunnerConfig(
        timeout=raw["runner"]["timeout"],
        cooldown=raw["runner"]["cooldown"],
        kill_before_run=raw["runner"]["kill_before_run"],
    )

    # 驗證 MT4 路徑
    if not Path(mt4.terminal_path).exists():
        raise FileNotFoundError(f"找不到 MT4 terminal：{mt4.terminal_path}")

    return AppConfig(mt4=mt4, backtest=backtest, paths=paths, runner=runner)
