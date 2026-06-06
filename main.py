import sys
import shutil
import time
import logging
from pathlib import Path
from datetime import datetime

# 確保專案目錄在模組搜尋路徑中（內嵌式 Python 需要）
sys.path.insert(0, str(Path(__file__).parent))

from src.config_loader import load_config
from dataclasses import replace
from src.set_parser import parse_set_file, parse_set_filename, discover_set_files
from src.ini_generator import generate_ini, generate_ea_ini
from src.mt4_runner import run_backtest, wait_for_report_file
from src.report_parser import parse_report
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
        rel_display = set_file.relative_to(config.paths.settings_dir)
        logger.info(f"[{idx}/{len(set_files)}] {rel_display}")
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
            # Note: MT4 Tester spread is controlled by TestSpread in the startup ini.
            # We support a simple convention: include one of these keys in the .set:
            #   spread=700   (or Spread=700 / TESTSPREAD=700)
            spread_keys = ("TestSpread", "TESTSPREAD", "spread", "Spread", "SPREAD")
            spread_raw = next((params.get(k) for k in spread_keys if k in params), None)
            if spread_raw is not None:
                try:
                    spread_val = int(float(str(spread_raw).strip()))
                    bt_config = replace(bt_config, spread=spread_val)
                    logger.info(f"從 .set 讀取 spread：{spread_raw} -> TestSpread={spread_val}")
                except ValueError:
                    logger.warning(f".set 的 spread 無法解析（忽略）：{spread_raw}")

            # 4b. 報告路徑
            # MT4 的 TestReport 相對路徑是相對於 data directory
            # 報告名稱用簡短格式避免 MT4 處理長檔名或特殊字元問題
            report_name = f"report_{idx}"
            mt4_data_dir = Path(config.mt4.data_dir)
            mt4_report_htm = mt4_data_dir / f"{report_name}.htm"
            mt4_report_gif = mt4_data_dir / f"{report_name}.gif"

            # 最終複製到的目的地：按 .set 所在子目錄映射到報告目錄
            # e.g. settings/sub1/file.set → results/reports/sub1/file.htm
            rel_subfolder = set_file.parent.relative_to(config.paths.settings_dir)
            final_report_dir = config.paths.reports_dir / rel_subfolder
            final_report_dir.mkdir(parents=True, exist_ok=True)

            # 4c. 產生 ini（寫入 MT4 資料目錄）
            ini_path = str(Path(config.mt4.data_dir) / "backtest_auto.ini")
            generate_ini(bt_config, report_name, ini_path)
            logger.info(f"INI 已產生：{ini_path}")

            # 4c2. 產生 EA 參數檔（寫入 tester 目錄）
            ea_ini_path = str(Path(config.mt4.data_dir) / "tester" / f"{bt_config.expert}.ini")
            generate_ea_ini(bt_config, str(set_file), ea_ini_path)
            logger.info(f"EA 參數檔已產生：{ea_ini_path}")

            # 4d. 執行回測
            success = run_backtest(
                terminal_path=config.mt4.terminal_path,
                ini_path=ini_path,
                timeout=config.runner.timeout,
                kill_before=config.runner.kill_before_run,
            )

            if not success:
                logger.error(f"回測失敗：{set_file.name}")
                failed.append(set_file.name)
                continue

            # 4e. 驗證報告並複製到結果目錄
            # MT4 可能先結束 process 再寫完 .htm，需短暫輪詢避免偶發找不到檔案
            if not wait_for_report_file(
                mt4_report_htm,
                timeout=float(config.runner.report_wait_timeout),
                poll=config.runner.report_poll_interval,
            ):
                logger.error(f"報告未產生（逾時 {config.runner.report_wait_timeout}s）：{mt4_report_htm}")
                failed.append(set_file.name)
                continue

            logger.info(f"報告已產生：{mt4_report_htm}")

            # 複製報告到結果目錄
            final_htm = str(final_report_dir / f"{set_file.stem}.htm")
            shutil.copy2(str(mt4_report_htm), final_htm)
            logger.info(f"報告已複製到：{final_htm}")

            # 刪除 MT4 目錄下的暫存報告
            mt4_report_htm.unlink(missing_ok=True)
            mt4_report_gif.unlink(missing_ok=True)

            # 4f. 解析報告
            result = parse_report(final_htm, set_file.name, config, bt_config)
            if result:
                results.append(result)
                logger.info(
                    f"淨利潤：{result.total_net_profit}  "
                    f"PF：{result.profit_factor}  "
                    f"回撤：{result.maximal_drawdown} ({result.maximal_drawdown_pct}%)"
                )
            else:
                logger.error(f"報告解析失敗：{final_htm}")
                failed.append(set_file.name)

        except Exception as e:
            logger.exception(f"處理 {set_file.name} 時發生錯誤：{e}")
            failed.append(set_file.name)

        # 4g. 回測間隔
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
