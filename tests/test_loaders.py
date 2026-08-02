"""
輸入格式測試：.xlsx / .xls / .csv 與不支援格式的處理。

重點在**不支援的檔案不能被靜默略過**。原本只掃 `*.xlsx`，3 個檔案的目錄
只看到 1 個且零警告——決賽 11 份混了舊格式時會安靜地只算一部分，
產出看起來完整、實則缺料的分析。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog_builder import detect_structure  # noqa: E402
from src.catalog_builder.loaders import (  # noqa: E402
    SUPPORTED_SUFFIXES,
    UnsupportedFormatError,
    _coerce,
    iter_workbooks,
    open_workbook,
    scan_inputs,
)
from src.catalog_builder.normalizer import normalize_sheet  # noqa: E402

ROWS = [
    ["歷年來臺旅客測試表", "", "", ""],
    ["年度", "日本", "韓國", "總計"],
    ["112年2023", "926140", "1010035", "6486951"],
    ["113年2024", "1318372", "1003086", "7857686"],
    ["114年2025", "1479392", "1100000", "8000000"],
]


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "測試.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(ROWS)
    return path


@pytest.fixture
def xls_file(tmp_path: Path) -> Path:
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook()
    sheet = book.add_sheet("舊格式")
    sheet.write_merge(0, 0, 0, 3, "歷年來臺旅客測試表")
    sheet.write_merge(1, 1, 1, 2, "亞洲地區")
    for col, name in enumerate(["年度", "日本", "韓國", "總計"]):
        sheet.write(2, col, name)
    for i, row in enumerate(ROWS[2:]):
        sheet.write(3 + i, 0, row[0])
        for col, value in enumerate(row[1:], start=1):
            sheet.write(3 + i, col, int(value))
    path = tmp_path / "舊格式.xls"
    book.save(str(path))
    return path


# --------------------------------------------------------------------------
# 掃描：不支援的檔案必須被大聲報出來
# --------------------------------------------------------------------------

def test_不支援格式不得靜默略過(tmp_path, csv_file):
    (tmp_path / "報表.ods").write_text("x", encoding="utf-8")
    scan = scan_inputs(tmp_path)
    assert [p.name for p in scan.supported] == ["測試.csv"]
    assert [p.name for p in scan.unsupported] == ["報表.ods"]
    assert scan.warnings and "未納入分析" in scan.warnings[0]
    assert "報表.ods" in scan.warnings[0]


def test_略過excel暫存檔(tmp_path, csv_file):
    """Excel 開啟中會產生 ~$ 開頭的暫存檔，那不是使用者的資料。"""
    (tmp_path / "~$測試.xlsx").write_text("x", encoding="utf-8")
    assert [p.name for p in scan_inputs(tmp_path).supported] == ["測試.csv"]


def test_目錄全空時明確報錯(tmp_path):
    with pytest.raises(FileNotFoundError, match="沒有可解析的資料檔"):
        list(iter_workbooks(tmp_path))


def test_警告會隨工作簿一起傳出(tmp_path, csv_file):
    (tmp_path / "報表.ods").write_text("x", encoding="utf-8")
    _, _, warnings = next(iter(iter_workbooks(tmp_path)))
    assert any("報表.ods" in w for w in warnings)


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

def test_csv走完整解析路徑(csv_file):
    """CSV 每格都是字串，若不轉型會被判定成整張表都是文字而解析失敗。"""
    worksheet = open_workbook(csv_file)["測試"]
    structure = detect_structure(worksheet)
    assert structure.is_parsable
    assert structure.title_rows == [1]
    assert structure.header_rows == [2]
    assert structure.data_start_row == 3

    normalized = normalize_sheet(structure, csv_file.name)
    japan = [r for r in normalized.records if r.period == 2024 and "日本" in r.dimension]
    assert japan and japan[0].value == 1318372.0


def test_csv支援cp950編碼(tmp_path):
    """政府開放資料的 CSV 常是 cp950，用 utf-8 讀會拋 UnicodeDecodeError。"""
    path = tmp_path / "big5.csv"
    with path.open("w", encoding="cp950", newline="") as handle:
        csv.writer(handle).writerows([["年度", "人次"], ["2024", "100"]])
    worksheet = open_workbook(path)["big5"]
    assert worksheet.cell(1, 1).value == "年度"


def test_數字字串轉型():
    assert _coerce("1318372") == 1318372.0
    assert _coerce("1,318,372") == 1318372.0   # 千分位
    assert _coerce("(1,234)") == -1234.0       # 會計負數格式
    assert _coerce("  ") is None
    assert _coerce("日本 Japan") == "日本 Japan"


# --------------------------------------------------------------------------
# .xls
# --------------------------------------------------------------------------

def test_xls讀得到合併儲存格(xls_file):
    """
    xlrd 預設 formatting_info=False 時 merged_cells 是空的。

    少了合併資訊，「亞洲地區」橫跨的欄位拿不到上層語意，
    多層表頭就解析不完整。
    """
    worksheet = open_workbook(xls_file)["舊格式"]
    ranges = {str(m) for m in worksheet.merged_cells.ranges}
    assert ranges == {"A1:D1", "B2:C2"}


def test_xls多層表頭正確合併(xls_file):
    worksheet = open_workbook(xls_file)["舊格式"]
    structure = detect_structure(worksheet)
    assert structure.title_rows == [1]
    assert structure.header_rows == [2, 3]
    names = {c.letter: c.full_name for c in structure.columns}
    assert names["B"] == "亞洲地區 > 日本"
    assert names["D"] == "總計"


def test_xls數值與座標正確(xls_file):
    structure = detect_structure(open_workbook(xls_file)["舊格式"])
    normalized = normalize_sheet(structure, xls_file.name)
    japan = [r for r in normalized.records if r.period == 2024 and "日本" in r.dimension]
    assert japan[0].value == 1318372.0
    assert japan[0].cell.a1 == "B5"


# --------------------------------------------------------------------------
# 混合目錄
# --------------------------------------------------------------------------

def test_混合格式全部納入(tmp_path, csv_file, xls_file):
    seen = {path.name for path, _, _ in iter_workbooks(tmp_path)}
    assert seen == {"測試.csv", "舊格式.xls"}


def test_未知副檔名明確報錯(tmp_path):
    path = tmp_path / "資料.parquet"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match="不支援"):
        open_workbook(path)


def test_支援清單涵蓋常見格式():
    assert {".xlsx", ".xls", ".csv"} <= SUPPORTED_SUFFIXES