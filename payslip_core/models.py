"""Plain data containers shared by the core modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

ERROR, WARNING, INFO = "error", "warning", "info"


@dataclass
class Flag:
    level: str
    message: str
    code: str = ""


@dataclass
class Line:
    label: str
    amount: Decimal
    source: str = ""        # e.g. 'AH' (column), 'comment', 'edited', 'manual'


@dataclass
class ColumnInfo:
    index: int
    letter: str
    header: str
    key: str
    role: str
    label: str


@dataclass
class Cell:
    value: Any = None
    formula: Optional[str] = None
    comment: str = ""
    is_error: bool = False


@dataclass
class RawRow:
    row: int
    cells: Dict[int, Cell] = field(default_factory=dict)


@dataclass
class SheetData:
    sheet_name: str
    sheet_names: List[str]
    header_row: int
    columns: List[ColumnInfo]
    rows: List[RawRow]
    stray: List[Tuple[int, str, str]] = field(default_factory=list)   # (row, column letter, text)
    global_flags: List[Flag] = field(default_factory=list)
    recalculated: bool = False


@dataclass
class LeaveInfo:
    cell_amount: Optional[Decimal] = None
    comment: str = ""
    status: str = "none"
    source: str = ""                       # how the printed entries were obtained
    parsed: List[Tuple[str, Decimal]] = field(default_factory=list)
    used: List[Line] = field(default_factory=list)


@dataclass
class Payslip:
    row: int
    emp_id: str
    name: str
    pan: str = ""
    attendance: List[Tuple[str, str]] = field(default_factory=list)
    income: List[Line] = field(default_factory=list)
    deductions: List[Line] = field(default_factory=list)
    flags: List[Flag] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    wb_total: Optional[Decimal] = None
    wb_net: Optional[Decimal] = None
    calc_total_before_tax: Decimal = Decimal(0)
    include_default: bool = True
    leave: List[LeaveInfo] = field(default_factory=list)

    @property
    def total_income(self) -> Decimal:
        return sum((l.amount for l in self.income), Decimal(0))

    @property
    def total_deductions(self) -> Decimal:
        return sum((l.amount for l in self.deductions), Decimal(0))

    @property
    def net_salary(self) -> Decimal:
        return self.total_income - self.total_deductions

    @property
    def errors(self) -> List[Flag]:
        return [f for f in self.flags if f.level == ERROR]

    @property
    def warnings(self) -> List[Flag]:
        return [f for f in self.flags if f.level == WARNING]
