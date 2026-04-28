import sys
import shutil
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

# 確保專案目錄在模組搜尋路徑中（內嵌式 Python 需要）
sys.path.insert(0, str(Path(__file__).parent))

from src.config_loader import load_config
from dataclasses import replace
from src.set_parser import parse_set_file, parse_set_filename, discover_set_files
from src.ini_generator import generate_ini, generate_ea_ini
from src.mt4_runner import run_backtest, wait_for_report_file
from src.report_parser import parse_report, extract_last_trade_date
from src.excel_writer import write_results


def _has_weekday(start_date, end_date) -> bool:
    """Return True if [start_date, end_date] contains at least one weekday (Mon–Fri)."""
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:
            return True
        d += timedelta(days=1)
    return False


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


def main():
    project_dir = Path(__file__).parent
    config_path = project_dir / "config.yaml"

    # 1. 載入設定
    try:
        config = load_config(str(config_path))
    except FileNotFoundError as e:
        print(f"[錯誤] {e}")
        sys.exit(1)

    # 設定日誌
    setup_logging(config.paths.results_dir / "logs")
    logger = logging.getLogger(__name__)

    # 2. 建立輸出目錄
    config.paths.results_dir.mkdir(parents=True, exist_ok=True)
    config.paths.reports_dir.mkdir(parents=True, exist_ok=True)

    # 3. 掃描所有 .set 檔案
    set_files = discover_set_files(str(config.paths.settings_dir))
    if not set_files:
        logger.error(f"找不到任何 .set 檔案：{config.paths.settings_dir}")
        sys.exit(1)

    logger.info(f"找到 {len(set_files)} 個 .set 檔案：")
    for f in set_files:
        logger.info(f"  - {f.name}")

    logger.info(f"預設 EA：{config.backtest.expert}")
    logger.info(f"預設幣對：{config.backtest.symbol}  週期：{config.backtest.period}")
    logger.info(f"（各 .set 檔名如含回測資訊，將自動覆蓋以上預設值）")

    # 4. 逐一執行回測
    results = []
    failed = []

    for idx, set_file in enumerate(set_files, 1):
        logger.info(f"\n{'='*50}")
        logger.info(f"[{idx}/{len(set_files)}] {set_file.name}")
        logger.info(f"{'='*50}")

        try:
            # 4a. 解析 .set 檔名取得回測參數
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
                logger.info(f"從檔名解析：EA={bt_config.expert} 幣對={bt_config.symbol} "
                            f"週期={bt_config.period} 日期={bt_config.from_date}~{bt_config.to_date} Spread={bt_config.spread}")
            else:
                bt_config = config.backtest
                logger.warning(f"檔名格式不符，使用 config.yaml 預設值")

            # 4a2. Symbol mapping（例如 HKGIDXHKD -> HK50ft.r）
            mapped_symbol = config.symbol_map.get(bt_config.symbol, bt_config.symbol)
            if mapped_symbol != bt_config.symbol:
                logger.info(f"Symbol 映射：{bt_config.symbol} -> {mapped_symbol}")
                bt_config = replace(bt_config, symbol=mapped_symbol)

            # 解析 .set 檔內容
            params = parse_set_file(str(set_file))
            logger.info(f"EA 參數：{params}")

            # 4a3. Spread override from .set file (optional)
            spread_keys = ("TestSpread", "TESTSPREAD", "spread", "Spread", "SPREAD")
            spread_raw = next((params.get(k) for k in spread_keys if k in params), None)
            if spread_raw is not None:
                try:
                    spread_val = int(float(str(spread_raw).strip()))
                    bt_config = replace(bt_config, spread=spread_val)
                    logger.info(f"從 .set 讀取 spread：{spread_raw} -> TestSpread={spread_val}")
                except ValueError:
                    logger.warning(f".set 的 spread 無法解析（忽略）：{spread_raw}")

            # 4b. Multi-cycle backtest loop
            # Each cycle runs from cycle_from_date to original_to_date.
            # If the EA closes all trades before original_to_date (e.g. hits TEP), the
            # report is renamed to reflect the actual end date and the next cycle begins
            # from (last_trade_date + 1 day).  Cycling stops when:
            #   • the last trade date reaches / exceeds original_to_date, or
            #   • the report contains 0 trades.
            # If the filename could not be parsed (filename_params is None) we fall back
            # to a single run with no renaming, matching the previous behaviour.
            original_to_date = bt_config.to_date          # e.g. "2024.12.31"
            original_to_date_obj = datetime.strptime(original_to_date, "%Y.%m.%d").date()
            cycle_from_date = bt_config.from_date          # advances each cycle
            can_cycle = filename_params is not None        # need parseable filename for renaming
            mt4_data_dir = Path(config.mt4.data_dir)
            final_report_dir = config.paths.reports_dir
            ini_path = str(mt4_data_dir / "backtest_auto.ini")
            set_had_error = False
            cycle_num = 0

            while True:
                cycle_num += 1

                # Unique short report name for this cycle (avoids long-path issues in MT4)
                report_name = f"report_{idx}_{cycle_num}"
                mt4_report_htm = mt4_data_dir / f"{report_name}.htm"
                mt4_report_gif = mt4_data_dir / f"{report_name}.gif"

                bt_config_cycle = replace(bt_config, from_date=cycle_from_date, to_date=original_to_date)

                if cycle_num == 1:
                    logger.info(f"週期 1：{cycle_from_date} → {original_to_date}")
                else:
                    logger.info(f"\n--- 週期 {cycle_num}：{cycle_from_date} → {original_to_date} ---")

                # 4c. 產生 ini
                generate_ini(bt_config_cycle, report_name, ini_path)
                logger.info(f"INI 已產生：{ini_path}")

                ea_ini_path = str(mt4_data_dir / "tester" / f"{bt_config_cycle.expert}.ini")
                generate_ea_ini(bt_config_cycle, str(set_file), ea_ini_path)
                logger.info(f"EA 參數檔已產生：{ea_ini_path}")

                # 4d. 執行回測
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

                # 4e. 等待報告寫入完成
                if not wait_for_report_file(
                    mt4_report_htm,
                    timeout=float(config.runner.report_wait_timeout),
                    poll=config.runner.report_poll_interval,
                ):
                    logger.error(f"報告未產生（逾時 {config.runner.report_wait_timeout}s，週期 {cycle_num}）：{mt4_report_htm}")
                    failed.append(f"{set_file.name} [週期{cycle_num}]")
                    set_had_error = True
                    break

                logger.info(f"報告已產生：{mt4_report_htm}")

                # 4e2. 從報告萃取最後交易時間，用於決定週期結束日與下一週期起始日
                last_trade_dt = extract_last_trade_date(str(mt4_report_htm))

                if last_trade_dt is not None:
                    actual_to_str = last_trade_dt.strftime("%Y%m%d")      # "20240220"
                    actual_to_date = last_trade_dt.strftime("%Y.%m.%d")   # "2024.02.20"
                    logger.info(f"最後交易時間：{last_trade_dt}")
                else:
                    # 無法偵測最後交易時間，以原始結束日作為本週期結束日
                    actual_to_str = original_to_date.replace(".", "")
                    actual_to_date = original_to_date
                    logger.warning(f"無法從報告偵測最後交易時間，使用原始結束日 {original_to_date}")

                # 4e3. 決定報告檔名（含實際週期起止日）
                cycle_from_str = cycle_from_date.replace(".", "")  # "2024.01.01" → "20240101"
                if can_cycle:
                    cycle_stem = build_cycle_report_stem(set_file.stem, cycle_from_str, actual_to_str)
                else:
                    cycle_stem = set_file.stem

                # 4f. 複製報告到結果目錄，刪除 MT4 暫存檔
                final_htm = str(final_report_dir / f"{cycle_stem}.htm")
                shutil.copy2(str(mt4_report_htm), final_htm)
                logger.info(f"報告已複製到：{final_htm}")
                mt4_report_htm.unlink(missing_ok=True)
                mt4_report_gif.unlink(missing_ok=True)

                # 4g. 解析報告（以實際週期結束日更新 bt_config）
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

                # 4h. 判斷是否需要下一週期
                if not can_cycle:
                    break  # 檔名無法解析，無法繼續週期

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

                # Guard: if the remaining window contains only weekends (e.g. Dec 30–31
                # both fall on Sat/Sun), MT4 has no tick data and will freeze with an
                # error dialog — skip the cycle instead of launching MT4.
                if not _has_weekday(next_from, original_to_date_obj):
                    logger.info(
                        f"週期 {cycle_num}：下一週期 {next_from} ~ {original_to_date_obj} "
                        f"全為週末無交易日，停止週期。"
                    )
                    break

                cycle_from_date = next_from.strftime("%Y.%m.%d")

                # 週期間隔
                logger.info(f"等待 {config.runner.cooldown} 秒後開始週期 {cycle_num + 1}...")
                time.sleep(config.runner.cooldown)

            if not set_had_error:
                logger.info(f"完成 {set_file.name}，共 {cycle_num} 個週期。")

        except Exception as e:
            logger.exception(f"處理 {set_file.name} 時發生錯誤：{e}")
            failed.append(set_file.name)

        # Set 檔間隔
        if idx < len(set_files):
            logger.info(f"等待 {config.runner.cooldown} 秒...")
            time.sleep(config.runner.cooldown)

    # 5. 寫入 Excel
    if results:
        excel_path = str(config.paths.excel_path)
        write_results(results, excel_path)
        logger.info(f"\nExcel 已儲存：{excel_path}")

    # 6. 摘要
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
