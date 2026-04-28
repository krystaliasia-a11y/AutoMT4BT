import re
from pathlib import Path
from src.config_loader import BacktestConfig


def generate_ini(
    config: BacktestConfig,
    report_path: str,
    output_path: str,
) -> str:
    """
    產生 MT4 startup config 檔案。
    MT4 的 config 檔是扁平 key=value 格式（無 section header）。
    必須用 ASCII 編碼。
    EA 參數不放在這裡，而是透過 generate_ea_ini() 寫入 tester/{EA}.ini。
    """
    lines = [
        "; Common settings",
        "ExpertsEnable=true",
        "ExpertsDllImport=true",
        "ExpertsExpImport=true",
        "ExpertsTrades=true",
        "",
        "; Strategy Tester settings",
        f"TestExpert={config.expert}",
        f"TestSymbol={config.symbol}",
        f"TestPeriod={config.period}",
        f"TestModel={config.model}",
        f"TestSpread={config.spread}",
        "TestOptimization=false",
        "TestDateEnable=true",
        f"TestFromDate={config.from_date}",
        f"TestToDate={config.to_date}",
        f"TestReport={report_path}",
        "TestReplaceReport=true",
        "TestShutdownTerminal=true",
        "TestVisualEnable=false",
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(lines) + "\n")

    return output_path


def generate_ea_ini(
    config: BacktestConfig,
    set_file_path: str,
    output_path: str,
) -> str:
    """
    產生 MT4 tester 用的 EA 參數檔案（tester/{EA名}.ini）。
    直接讀取 .set 檔內容作為 <inputs> 區段，
    包上 <common> 和 <limits> 區段。
    """
    # 讀取 .set 檔原始內容
    for encoding in ("utf-8", "cp1252"):
        try:
            with open(set_file_path, "r", encoding=encoding) as f:
                set_content = f.read().strip()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"無法讀取 .set 檔案：{set_file_path}")

    # incorrect_tick_popup=1 causes MT4's Strategy Tester to show a blocking
    # dialog when the EA detects a suspicious tick value. With
    # TestShutdownTerminal=true, this popup prevents the report from being
    # written before MT4 exits. Override to 0 to suppress the dialog;
    # the EA's tick-handling logic is unaffected.
    set_content = re.sub(
        r"^incorrect_tick_popup\s*=.*$",
        "incorrect_tick_popup=0",
        set_content,
        flags=re.MULTILINE,
    )

    lines = [
        "<common>",
        "positions=2",
        f"deposit={config.deposit}",
        f"currency={config.currency}",
        "fitnes=0",
        "genetic=1",
        "</common>",
        "",
        "<inputs>",
        set_content,
        "</inputs>",
        "",
        "<limits>",
        "balance_enable=0",
        "balance=200.00",
        "profit_enable=0",
        "profit=10000.00",
        "marginlevel_enable=0",
        "marginlevel=30.00",
        "maxdrawdown_enable=0",
        "maxdrawdown=70.00",
        "consecloss_enable=0",
        "consecloss=5000.00",
        "conseclossdeals_enable=0",
        "conseclossdeals=10.00",
        "consecwin_enable=0",
        "consecwin=10000.00",
        "consecwindeals_enable=0",
        "consecwindeals=30.00",
        "</limits>",
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(lines) + "\n")

    return output_path
