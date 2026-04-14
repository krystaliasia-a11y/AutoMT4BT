import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


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


@dataclass
class AutoGenerateConfig:
    """Configuration for the dynamic set-file generation mode (auto_generate.enabled=1).

    When enabled the program fetches live price data, calculates boundaries,
    generates .set files, and cycles through years automatically.
    """
    enabled: bool
    start_year: int
    end_year: int
    pairs: list
    template_file: Path
    ea_name: str
    # SRM EA parameters
    equity_assumption: str
    real_equity: str
    tep_var: str
    opt_tep: str
    take_profit_ratio: str
    pullback_ratio: str
    drop_ratio: str
    brounce_ratio: str
    open_order_buffer_pct: float
    enable_buy_order: str
    enable_sell_order: str
    max_instant_order_level: str
    max_orders_per_side: str
    margin_level_to_open_new_orders: str
    magic_number_start: Optional[int]
    # MT4 parameters
    spread: str
    time_frame: str
    # Yahoo Finance symbol overrides
    yf_symbol_map: dict = field(default_factory=dict)


@dataclass
class AppConfig:
    mt4: MT4Config
    backtest: BacktestConfig
    paths: PathsConfig
    runner: RunnerConfig
    symbol_map: dict
    auto_generate: AutoGenerateConfig


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
    )

    symbol_map = raw.get("symbol_map", {}) or {}
    if not isinstance(symbol_map, dict):
        raise ValueError("config.yaml 的 symbol_map 必須是 key/value 的對照表（dict）")

    # ── auto_generate section (optional; defaults to disabled) ─────────────
    ag_raw = raw.get("auto_generate", {}) or {}
    ag_enabled = int(ag_raw.get("enabled", 0)) == 1

    template_rel = ag_raw.get("template_file", "config/template.set")
    template_file = (base_dir / template_rel).resolve()

    yf_map = ag_raw.get("yf_symbol_map", {}) or {}
    if not isinstance(yf_map, dict):
        raise ValueError("auto_generate.yf_symbol_map must be a dict")

    magic_raw = ag_raw.get("magic_number_start", None)
    magic_number_start = int(magic_raw) if magic_raw is not None else None

    auto_generate = AutoGenerateConfig(
        enabled=ag_enabled,
        start_year=int(ag_raw.get("start_year", 2024)),
        end_year=int(ag_raw.get("end_year", 2024)),
        pairs=list(ag_raw.get("pairs", [])),
        template_file=template_file,
        ea_name=str(ag_raw.get("ea_name", "SRM_v6.0_AlgoX_REAL")),
        equity_assumption=str(ag_raw.get("equity_assumption", "30000")),
        real_equity=str(ag_raw.get("real_equity", "10000")),
        tep_var=str(ag_raw.get("tep_var", "20")),
        opt_tep=str(ag_raw.get("opt_tep", "0")),
        take_profit_ratio=str(ag_raw.get("take_profit_ratio", "1.8")),
        pullback_ratio=str(ag_raw.get("pullback_ratio", "0.8")),
        drop_ratio=str(ag_raw.get("drop_ratio", "1.5")),
        brounce_ratio=str(ag_raw.get("brounce_ratio", "1.0")),
        open_order_buffer_pct=float(ag_raw.get("open_order_buffer_pct", 30)),
        enable_buy_order=str(ag_raw.get("enable_buy_order", "1")),
        enable_sell_order=str(ag_raw.get("enable_sell_order", "1")),
        max_instant_order_level=str(ag_raw.get("max_instant_order_level", "2")),
        max_orders_per_side=str(ag_raw.get("max_orders_per_side", "111")),
        margin_level_to_open_new_orders=str(ag_raw.get("margin_level_to_open_new_orders", "150")),
        magic_number_start=magic_number_start,
        spread=str(ag_raw.get("spread", "15")),
        time_frame=str(ag_raw.get("time_frame", "H1")),
        yf_symbol_map=yf_map,
    )

    # 驗證 MT4 路徑
    if not Path(mt4.terminal_path).exists():
        raise FileNotFoundError(f"找不到 MT4 terminal：{mt4.terminal_path}")

    return AppConfig(
        mt4=mt4,
        backtest=backtest,
        paths=paths,
        runner=runner,
        symbol_map=symbol_map,
        auto_generate=auto_generate,
    )
