"""
price_fetcher.py
~~~~~~~~~~~~~~~~
Fetches daily OHLC data from Yahoo Finance and calculates the dynamic
top/bottom boundaries used for set-file generation.

    top_boundary    = 120-day highest High  + 0.5 × ATR(20D)
    bottom_boundary = 120-day lowest  Low   − 0.5 × ATR(20D)

ATR(20D) is the simple (non-smoothed) average of the True Range over the
most recent 20 daily bars ending just before *reference_date*.
"""

import logging
from datetime import date, timedelta
from typing import Tuple

logger = logging.getLogger(__name__)

# Extra calendar days to request so we always have >= 140 trading days
# even over holiday-heavy periods (roughly 1.5× the needed trading days).
_FETCH_BUFFER_DAYS = 220


def _to_yf_symbol(pair: str, yf_map: dict) -> str:
    """Map a trading-pair name to the Yahoo Finance ticker string.

    Explicit overrides in *yf_map* take precedence.  Forex pairs that are
    not overridden are tried as ``PAIR=X`` (the standard Yahoo Finance
    convention, e.g. ``NZDCAD=X``).
    """
    if pair in yf_map:
        return yf_map[pair]
    return f"{pair}=X"


def _calc_atr(highs, lows, closes, period: int) -> float:
    """Return the simple ATR over the last *period* bars.

    True Range_i = max(H_i − L_i,
                       |H_i − C_{i-1}|,
                       |L_i − C_{i-1}|)
    """
    tr_values = []
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i] - closes[i - 1])
        tr_values.append(max(hl, hpc, lpc))

    if not tr_values:
        raise ValueError("Not enough bars to compute True Range")

    tail = tr_values[-period:] if len(tr_values) >= period else tr_values
    return sum(tail) / len(tail)


def fetch_boundaries(
    pair: str,
    reference_date: date,
    yf_map: dict,
) -> Tuple[float, float]:
    """Return (top_boundary, bottom_boundary) based on data up to *reference_date*.

    Parameters
    ----------
    pair:           Trading pair symbol as used in the EA / set-file names.
    reference_date: The cycle start date.  Data is fetched for the 120+
                    trading days ending on (but not including) this date.
    yf_map:         Dict mapping pair names to Yahoo Finance ticker overrides.

    Returns
    -------
    (top_boundary, bottom_boundary) as floats.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError(
            "yfinance is required for auto_generate mode. "
            "Install with: pip install yfinance"
        ) from exc

    yf_sym = _to_yf_symbol(pair, yf_map)
    fetch_start = reference_date - timedelta(days=_FETCH_BUFFER_DAYS)

    logger.info(
        f"Fetching {pair} ({yf_sym}) "
        f"{fetch_start} → {reference_date} for boundary calculation"
    )

    ticker = yf.Ticker(yf_sym)
    df = ticker.history(
        start=fetch_start.strftime("%Y-%m-%d"),
        end=reference_date.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=True,
    )

    if df.empty:
        raise ValueError(
            f"No price data returned for {yf_sym} up to {reference_date}. "
            "Check the symbol name or Yahoo Finance availability."
        )

    # Work with the last 121 rows: the oldest row only supplies Close for
    # the TR calculation of the following row, so we get up to 120 TR values.
    df = df.tail(121)

    highs = df["High"].tolist()
    lows = df["Low"].tolist()
    closes = df["Close"].tolist()

    if len(highs) < 21:
        raise ValueError(
            f"Insufficient history for {yf_sym}: got {len(highs)} bars, "
            "need at least 21 (20 ATR bars + 1 for previous close)."
        )

    # 120-day price range (exclude the very first row which is only a Close anchor)
    range_highs = highs[1:]
    range_lows = lows[1:]
    high_120 = max(range_highs[-120:])
    low_120 = min(range_lows[-120:])

    # ATR(20D) — uses last 20 TR values
    atr_20 = _calc_atr(highs, lows, closes, period=20)

    top_boundary = high_120 + 0.5 * atr_20
    bottom_boundary = low_120 - 0.5 * atr_20

    logger.info(
        f"{pair} ({yf_sym}): "
        f"120D High={high_120:.8f}  120D Low={low_120:.8f}  ATR(20D)={atr_20:.8f}"
    )
    logger.info(
        f"  → top_boundary={top_boundary:.8f}  "
        f"bottom_boundary={bottom_boundary:.8f}"
    )

    return top_boundary, bottom_boundary
