import sys
import shutil
import time
import logging
from pathlib import Path
from datetime import date, datetime, timedelta

# 確保專案目錄在模組搜尋路徑中（內嵌式 Python 需要）
sys.path.insert(0, str(Path(__file__).parent))

from src.config_loader import load_config, AutoGenerateConfig
from dataclasses import replace
from src.set_parser import parse_set_file, parse_set_filename, discover_set_files
from src.ini_generator import generate_ini, generate_ea_ini
from src.mt4_runner import run_backtest, wait_for_report_file
from src.report_parser import parse_report, extract_last_trade_date
from src.excel_writer import write_results


def setup_logging(log_dir: Path):
    """設定日誌：同時輸出到 console 和檔案"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(log_file), encoding="utf-8"),
        ],
    )


def build_cycle_report_stem(set_stem: str, from_date_str: str, to_date_str: str) -> str:
    """Replace the date tokens in a set file stem with the given cycle dates.

    Handles both filename formats parsed by parse_set_filename:
      New (7+ parts): EA-Symbol-Period-FromDate-ToDate-Spread-Version
      Old (6 parts):  EA-Symbol-Period-FromDate-ToDate-Version

    from_date_str / to_date_str must be in YYYYMMDD format.
    """
    parts = set_stem.split("-")
    if len(parts) >= 7:
        parts[-4] = from_date_str
        parts[-3] = to_date_str
    elif len(parts) >= 6:
        parts[-3] = from_date_str
        parts[-2] = to_date_str
    else:
        return set_stem  # unrecognised format — return unchanged
    return "-".join(parts)


# ── shared backtest execution ─────────────────────────────────────────────────

def run_single_set(
    config,
    set_file: Path,
    idx: int,
    results: list,
    failed: list,
    logger,
):
    """Run all cycles for one .set file and append results.

    This is the core loop shared by both regular and auto_generate modes.
    In regular mode the set file stays fixed; in auto_generate mode the
    caller replaces set_file on each outer cycle and passes cycle_num=1.
    """
    try:
        # Parse filename to extract backtest parameters
        filename_params = parse_set_filename(set_file.name)
        if filename_params:
            spread_from_name = filename_params.get("spread")
            if spread_from_name is None:
                spread_from_name = config.backtest.spread
            bt_config = replace(
                config.backtest,
                expert=filename_params["expert"],
                symbol=filename_params["symbol"],
                period=filename_params["period"],
                from_date=filename_params["from_date"],
                to_date=filename_params["to_date"],
                spread=spread_from_name,
            )
            logger.info(
                f"從檔名解析：EA={bt_config.expert} 幣對={bt_config.symbol} "
                f"週期={bt_config.period} 日期={bt_config.from_date}~{bt_config.to_date} "
                f"Spread={bt_config.spread}"
            )
        else:
            bt_config = config.backtest
            logger.warning("檔名格式不符，使用 config.yaml 預設值")

        # Symbol mapping
        mapped_symbol = config.symbol_map.get(bt_config.symbol, bt_config.symbol)
        if mapped_symbol != bt_config.symbol:
            logger.info(f"Symbol 映射：{bt_config.symbol} -> {mapped_symbol}")
            bt_config = replace(bt_config, symbol=mapped_symbol)

        # Parse .set file content
        params = parse_set_file(str(set_file))
        logger.info(f"EA 參數：{params}")

        # Spread override from .set file (optional)
        spread_keys = ("TestSpread", "TESTSPREAD", "spread", "Spread", "SPREAD")
        spread_raw = next((params.get(k) for k in spread_keys if k in params), None)
        if spread_raw is not None:
            try:
                spread_val = int(float(str(spread_raw).strip()))
                bt_config = replace(bt_config, spread=spread_val)
                logger.info(f"從 .set 讀取 spread：{spread_raw} -> TestSpread={spread_val}")
            except ValueError:
                logger.warning(f".set 的 spread 無法解析（忽略）：{spread_raw}")

        # Multi-cycle backtest loop
        original_to_date = bt_config.to_date
        original_to_date_obj = datetime.strptime(original_to_date, "%Y.%m.%d").date()
        cycle_from_date = bt_config.from_date
        can_cycle = filename_params is not None
        mt4_data_dir = Path(config.mt4.data_dir)
        final_report_dir = config.paths.reports_dir
        ini_path = str(mt4_data_dir / "backtest_auto.ini")
        set_had_error = False
        cycle_num = 0

        while True:
            cycle_num += 1

            report_name = f"report_{idx}_{cycle_num}"
            mt4_report_htm = mt4_data_dir / f"{report_name}.htm"
            mt4_report_gif = mt4_data_dir / f"{report_name}.gif"

            bt_config_cycle = replace(bt_config, from_date=cycle_from_date, to_date=original_to_date)

            if cycle_num == 1:
                logger.info(f"週期 1：{cycle_from_date} → {original_to_date}")
            else:
                logger.info(f"\n--- 週期 {cycle_num}：{cycle_from_date} → {original_to_date} ---")

            generate_ini(bt_config_cycle, report_name, ini_path)
            logger.info(f"INI 已產生：{ini_path}")

            ea_ini_path = str(mt4_data_dir / "tester" / f"{bt_config_cycle.expert}.ini")
            generate_ea_ini(bt_config_cycle, str(set_file), ea_ini_path)
            logger.info(f"EA 參數檔已產生：{ea_ini_path}")

            success = run_backtest(
                terminal_path=config.mt4.terminal_path,
                ini_path=ini_path,
                timeout=config.runner.timeout,
                kill_before=config.runner.kill_before_run,
            )
            if not success:
                logger.error(f"回測失敗（週期 {cycle_num}）：{set_file.name}")
                failed.append(f"{set_file.name} [週期{cycle_num}]")
                set_had_error = True
                break

            if not wait_for_report_file(
                mt4_report_htm,
                timeout=float(config.runner.report_wait_timeout),
                poll=config.runner.report_poll_interval,
            ):
                logger.error(
                    f"報告未產生（逾時 {config.runner.report_wait_timeout}s，"
                    f"週期 {cycle_num}）：{mt4_report_htm}"
                )
                failed.append(f"{set_file.name} [週期{cycle_num}]")
                set_had_error = True
                break

            logger.info(f"報告已產生：{mt4_report_htm}")

            last_trade_dt = extract_last_trade_date(str(mt4_report_htm))

            if last_trade_dt is not None:
                actual_to_str = last_trade_dt.strftime("%Y%m%d")
                actual_to_date = last_trade_dt.strftime("%Y.%m.%d")
                logger.info(f"最後交易時間：{last_trade_dt}")
            else:
                actual_to_str = original_to_date.replace(".", "")
                actual_to_date = original_to_date
                logger.warning(f"無法從報告偵測最後交易時間，使用原始結束日 {original_to_date}")

            cycle_from_str = cycle_from_date.replace(".", "")
            if can_cycle:
                cycle_stem = build_cycle_report_stem(set_file.stem, cycle_from_str, actual_to_str)
            else:
                cycle_stem = set_file.stem

            final_htm = str(final_report_dir / f"{cycle_stem}.htm")
            shutil.copy2(str(mt4_report_htm), final_htm)
            logger.info(f"報告已複製到：{final_htm}")
            mt4_report_htm.unlink(missing_ok=True)
            mt4_report_gif.unlink(missing_ok=True)

            bt_config_result = replace(bt_config_cycle, to_date=actual_to_date)
            result = parse_report(final_htm, f"{cycle_stem}.htm", config, bt_config_result)
            if result:
                results.append(result)
                logger.info(
                    f"[週期{cycle_num}] 淨利潤：{result.total_net_profit}  "
                    f"PF：{result.profit_factor}  "
                    f"交易數：{result.total_trades}  "
                    f"回撤：{result.maximal_drawdown} ({result.maximal_drawdown_pct}%)"
                )
            else:
                logger.error(f"報告解析失敗：{final_htm}")
                failed.append(f"{set_file.name} [週期{cycle_num}]")
                set_had_error = True
                break

            if not can_cycle:
                break

            if result.total_trades == 0:
                logger.info(f"週期 {cycle_num}：報告無交易，停止週期。")
                break

            if last_trade_dt is None or last_trade_dt.date() >= original_to_date_obj:
                logger.info(f"週期 {cycle_num}：已達原始結束日，停止週期。")
                break

            next_from = last_trade_dt.date() + timedelta(days=1)
            if next_from >= original_to_date_obj:
                logger.info(f"週期 {cycle_num}：下一週期起始日已達原始結束日，停止週期。")
                break

            cycle_from_date = next_from.strftime("%Y.%m.%d")

            logger.info(f"等待 {config.runner.cooldown} 秒後開始週期 {cycle_num + 1}...")
            time.sleep(config.runner.cooldown)

        if not set_had_error:
            logger.info(f"完成 {set_file.name}，共 {cycle_num} 個週期。")

        # Return the actual end date of the last cycle so the caller can
        # use it as the next outer-cycle start date (auto_generate mode).
        if last_trade_dt is not None:
            return last_trade_dt.date()
        return original_to_date_obj

    except Exception as e:
        logger.exception(f"處理 {set_file.name} 時發生錯誤：{e}")
        failed.append(set_file.name)
        return None


# ── auto_generate mode ────────────────────────────────────────────────────────

def run_auto_generate_mode(config, logger) -> tuple:
    """Dynamic flow: generate set files from live price data, then backtest.

    For each pair:
      1. Calculate top/bottom boundaries at cycle_start using online price data.
      2. Generate a .set file.
      3. Run the MT4 backtest from cycle_start to final_end_date.
      4. Use last_trade_date + 1 day as next cycle's start date.
      5. Regenerate the .set file with fresh boundaries, repeat.
      6. Stop when cycle_start >= final_end_date.

    Returns (results, failed).
    """
    from src.price_fetcher import fetch_boundaries
    from src.dynamic_set_generator import generate_set_file

    ag = config.auto_generate
    results = []
    failed = []

    final_end_date = date(ag.end_year, 12, 31)
    settings_dir = config.paths.settings_dir
    settings_dir.mkdir(parents=True, exist_ok=True)

    # Use a shared magic number counter across all pairs (increments per set file)
    import random
    magic_counter = ag.magic_number_start if ag.magic_number_start is not None \
        else random.randint(100000, 999999)

    logger.info(f"Auto-generate mode enabled.  Pairs: {ag.pairs}")
    logger.info(f"Date range: {ag.start_year}.01.01 → {ag.end_year}.12.31")

    for pair_idx, pair in enumerate(ag.pairs, 1):
        logger.info(f"\n{'='*50}")
        logger.info(f"[Pair {pair_idx}/{len(ag.pairs)}] {pair}")
        logger.info(f"{'='*50}")

        cycle_start = date(ag.start_year, 1, 1)
        outer_cycle = 0

        while cycle_start < final_end_date:
            outer_cycle += 1
            logger.info(
                f"\n[{pair}] Outer cycle {outer_cycle}: "
                f"{cycle_start} → {final_end_date}"
            )

            # 1. Fetch boundaries based on cycle_start
            try:
                top_boundary, bottom_boundary = fetch_boundaries(
                    pair=pair,
                    reference_date=cycle_start,
                    yf_map=ag.yf_symbol_map,
                )
            except Exception as e:
                logger.error(f"[{pair}] Failed to fetch boundaries for {cycle_start}: {e}")
                failed.append(f"{pair} [outer_cycle {outer_cycle}]")
                break

            # 2. Generate .set file
            try:
                set_file = generate_set_file(
                    pair=pair,
                    cycle_start=cycle_start,
                    cycle_end=final_end_date,
                    top_boundary=top_boundary,
                    bottom_boundary=bottom_boundary,
                    template_path=str(ag.template_file),
                    output_dir=str(settings_dir),
                    ea_name=ag.ea_name,
                    equity_assumption=ag.equity_assumption,
                    real_equity=ag.real_equity,
                    tep_var=ag.tep_var,
                    opt_tep=ag.opt_tep,
                    take_profit_ratio=ag.take_profit_ratio,
                    pullback_ratio=ag.pullback_ratio,
                    drop_ratio=ag.drop_ratio,
                    brounce_ratio=ag.brounce_ratio,
                    spread=ag.spread,
                    open_order_buffer_pct=ag.open_order_buffer_pct,
                    time_frame=ag.time_frame,
                    enable_buy_order=ag.enable_buy_order,
                    enable_sell_order=ag.enable_sell_order,
                    max_instant_order_level=ag.max_instant_order_level,
                    max_orders_per_side=ag.max_orders_per_side,
                    margin_level_to_open_new_orders=ag.margin_level_to_open_new_orders,
                    magic_number=magic_counter,
                )
                magic_counter += 1
            except Exception as e:
                logger.error(f"[{pair}] Failed to generate set file: {e}")
                failed.append(f"{pair} [outer_cycle {outer_cycle}]")
                break

            # 3. Run the MT4 backtest (inner multi-cycle for TEP hits)
            # Use a unique index so report filenames don't collide across pairs
            run_idx = pair_idx * 1000 + outer_cycle
            last_trade_date = run_single_set(
                config=config,
                set_file=set_file,
                idx=run_idx,
                results=results,
                failed=failed,
                logger=logger,
            )

            # Clean up the generated .set file from settings dir to keep it tidy
            try:
                set_file.unlink(missing_ok=True)
            except Exception:
                pass

            if last_trade_date is None:
                # run_single_set already logged the error
                break

            # 4. Advance to next outer cycle
            next_start = last_trade_date + timedelta(days=1)
            if next_start >= final_end_date:
                logger.info(
                    f"[{pair}] Outer cycle {outer_cycle} complete: "
                    f"reached end date {final_end_date}."
                )
                break

            logger.info(
                f"[{pair}] Outer cycle {outer_cycle} done.  "
                f"Next cycle starts {next_start}."
            )
            cycle_start = next_start

            logger.info(f"等待 {config.runner.cooldown} 秒...")
            time.sleep(config.runner.cooldown)

    return results, failed


# ── regular mode (pre-placed .set files) ─────────────────────────────────────

def run_regular_mode(config, logger) -> tuple:
    """Original flow: discover .set files in settings/ and run them."""
    set_files = discover_set_files(str(config.paths.settings_dir))
    if not set_files:
        logger.error(f"找不到任何 .set 檔案：{config.paths.settings_dir}")
        sys.exit(1)

    logger.info(f"找到 {len(set_files)} 個 .set 檔案：")
    for f in set_files:
        logger.info(f"  - {f.name}")

    logger.info(f"預設 EA：{config.backtest.expert}")
    logger.info(f"預設幣對：{config.backtest.symbol}  週期：{config.backtest.period}")
    logger.info("（各 .set 檔名如含回測資訊，將自動覆蓋以上預設值）")

    results = []
    failed = []

    for idx, set_file in enumerate(set_files, 1):
        logger.info(f"\n{'='*50}")
        logger.info(f"[{idx}/{len(set_files)}] {set_file.name}")
        logger.info(f"{'='*50}")

        run_single_set(config, set_file, idx, results, failed, logger)

        if idx < len(set_files):
            logger.info(f"等待 {config.runner.cooldown} 秒...")
            time.sleep(config.runner.cooldown)

    return results, failed


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    project_dir = Path(__file__).parent
    config_path = project_dir / "config.yaml"

    # 1. Load config
    try:
        config = load_config(str(config_path))
    except FileNotFoundError as e:
        print(f"[錯誤] {e}")
        sys.exit(1)

    # Setup logging
    setup_logging(config.paths.results_dir)
    logger = logging.getLogger(__name__)

    # 2. Create output directories
    config.paths.results_dir.mkdir(parents=True, exist_ok=True)
    config.paths.reports_dir.mkdir(parents=True, exist_ok=True)

    # 3. Dispatch to the appropriate mode
    if config.auto_generate.enabled:
        logger.info("Auto-generate mode is ENABLED (auto_generate.enabled=1)")
        results, failed = run_auto_generate_mode(config, logger)
    else:
        logger.info("Regular mode (auto_generate.enabled=0): using pre-placed .set files")
        results, failed = run_regular_mode(config, logger)

    # 4. Write Excel
    if results:
        excel_path = str(config.paths.excel_path)
        write_results(results, excel_path)
        logger.info(f"\nExcel 已儲存：{excel_path}")

    # 5. Summary
    logger.info(f"\n{'='*50}")
    logger.info(f"回測完成！成功：{len(results)}，失敗：{len(failed)}")
    if failed:
        logger.warning(f"失敗項目：{', '.join(failed)}")
    if results:
        logger.info(f"報告目錄：{config.paths.reports_dir}")
        logger.info(f"Excel 檔案：{config.paths.excel_path}")
    logger.info(f"{'='*50}")


if __name__ == "__main__":
    main()
