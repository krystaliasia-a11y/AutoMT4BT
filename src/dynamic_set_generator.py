"""
dynamic_set_generator.py
~~~~~~~~~~~~~~~~~~~~~~~~
Generates MT4 .set files from the SRM EA template by substituting live-
calculated price boundaries and EA configuration parameters.

This module mirrors the logic of BacktestSetFileGenerator/src/generate_sets.py
but accepts boundary values that were computed from online price data rather
than from a static CSV file.
"""

import logging
import random
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt_price(value: float) -> str:
    """Format a price level to 8 decimal places for .set file entries."""
    return f"{float(value):.8f}"


def _fmt_leverage(equity_assumption: str, real_equity: str) -> str:
    """Compute equity_assumption / real_equity as a compact filename-safe string."""
    eq = float(equity_assumption)
    re_val = float(real_equity)
    if re_val == 0:
        raise ValueError("real_equity must not be zero")
    v = eq / re_val
    s = f"{v:.8f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _open_order_thresholds(
    top_boundary: float,
    bottom_boundary: float,
    buffer_pct: float,
) -> tuple:
    """Return (open_buy_larger_than, open_sell_smaller_than).

    buffer_pct % of the range is trimmed from each end:
        larger_than  = bottom_boundary + margin   (buy entry above support)
        smaller_than = top_boundary    - margin   (sell entry below resistance)
    """
    span = top_boundary - bottom_boundary
    margin = span * buffer_pct / 100.0
    larger_than = bottom_boundary + margin
    smaller_than = top_boundary - margin
    return _fmt_price(larger_than), _fmt_price(smaller_than)


# ── public API ────────────────────────────────────────────────────────────────

def generate_set_file(
    pair: str,
    cycle_start: date,
    cycle_end: date,
    top_boundary: float,
    bottom_boundary: float,
    template_path: str,
    output_dir: str,
    ea_name: str,
    equity_assumption: str,
    real_equity: str,
    tep_var: str,
    opt_tep: str,
    take_profit_ratio: str,
    pullback_ratio: str,
    drop_ratio: str,
    brounce_ratio: str,
    spread: str,
    open_order_buffer_pct: float,
    time_frame: str,
    enable_buy_order: str,
    enable_sell_order: str,
    max_instant_order_level: str,
    max_orders_per_side: str,
    margin_level_to_open_new_orders: str,
    magic_number: Optional[int] = None,
) -> Path:
    """Generate a single .set file and write it to *output_dir*.

    Parameters
    ----------
    pair:               Trading pair symbol (e.g. ``NZDCAD``).
    cycle_start:        Backtest start date for this cycle.
    cycle_end:          Backtest end date for this cycle.
    top_boundary:       Calculated upper price boundary.
    bottom_boundary:    Calculated lower price boundary.
    template_path:      Absolute or relative path to the .set template file.
    output_dir:         Directory where the generated .set file is written.
    ea_name:            EA name used in the output filename (without .ex4).
    (remaining params): EA configuration values — see config.yaml.

    Returns
    -------
    Path to the written .set file.
    """
    template_file = Path(template_path)
    if not template_file.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        template_content = template_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        template_content = template_file.read_text(encoding="cp1252")

    if magic_number is None:
        magic_number = random.randint(100000, 999999)

    leverage_str = _fmt_leverage(equity_assumption, real_equity)
    ob_larger, ob_smaller = _open_order_thresholds(
        top_boundary, bottom_boundary, open_order_buffer_pct
    )

    # Build the output filename using the same convention as BacktestSetFileGenerator:
    # {ea_name}-{pair}-{timeframe}-{from_YYYYMMDD}-{to_YYYYMMDD}-{spread}-
    # TEP{tep}_TBBB{year}_TR{tp}PB{pb}DR{dr}BR{br}_Margin{leverage}X.set
    from_str = cycle_start.strftime("%Y%m%d")
    to_str = cycle_end.strftime("%Y%m%d")
    year_str = str(cycle_start.year)

    filename = (
        f"{ea_name}-{pair}-{time_frame}"
        f"-{from_str}-{to_str}-{spread}"
        f"-TEP{tep_var}_TBBB{year_str}"
        f"_TR{take_profit_ratio}PB{pullback_ratio}"
        f"DR{drop_ratio}BR{brounce_ratio}"
        f"_Margin{leverage_str}X.set"
    )

    # Replace all template placeholders
    content = template_content
    content = content.replace("{PriceHighest}",              _fmt_price(top_boundary))
    content = content.replace("{PriceLowest}",               _fmt_price(bottom_boundary))
    content = content.replace("{OpenBuyLargerThan}",         ob_larger)
    content = content.replace("{OpenBuySmallerThan}",        ob_smaller)
    content = content.replace("{OpenSellLargerThan}",        ob_larger)
    content = content.replace("{OpenSellSmallerThan}",       ob_smaller)
    content = content.replace("{Spread}",                    spread)
    content = content.replace("{EquityAssumption}",          equity_assumption)
    content = content.replace("{RealEquity}",                real_equity)
    content = content.replace("{TepVar}",                    tep_var)
    content = content.replace("{TakeProfitRatio}",           take_profit_ratio)
    content = content.replace("{PullbackRatio}",             pullback_ratio)
    content = content.replace("{DropRatio}",                 drop_ratio)
    content = content.replace("{BrounceRatio}",              brounce_ratio)
    content = content.replace("{Leverage}",                  leverage_str)
    content = content.replace("{MagicNumber}",               str(magic_number))
    content = content.replace("{timeFrame}",                 time_frame)
    content = content.replace("{EnableBuyOrder}",            enable_buy_order)
    content = content.replace("{EnableSellOrder}",           enable_sell_order)
    content = content.replace("{MaxInstantOrderLevel}",      max_instant_order_level)
    content = content.replace("{MaxOrdersPerSide}",          max_orders_per_side)
    content = content.replace("{OptTEP}",                    opt_tep)
    content = content.replace("{MarginLevelToOpenNewOrders}", margin_level_to_open_new_orders)
    content = content.replace("{CustomComment}",             filename)

    set_file_path = output_path / filename
    set_file_path.write_text(content, encoding="utf-8")

    logger.info(
        f"Generated set file: {set_file_path.name}  "
        f"(top={_fmt_price(top_boundary)}, bot={_fmt_price(bottom_boundary)}, "
        f"MagicNumber={magic_number})"
    )
    return set_file_path
