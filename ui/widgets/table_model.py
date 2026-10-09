"""Shared pandas-backed table model (numeric cells: Consolas 9pt, right-aligned)."""
import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, Qt
from PyQt6.QtGui import QFont


class PandasTableModel(QAbstractTableModel):
    """Table model for displaying pandas DataFrames."""

    def __init__(self, df: pd.DataFrame = None, parent=None, float_decimals=None):
        """float_decimals: int for all float columns, or {column name: int}; default 4."""
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()
        self._float_decimals = float_decimals

    def _decimals_for(self, col: int) -> int:
        spec = self._float_decimals
        if isinstance(spec, dict):
            return spec.get(str(self._df.columns[col]), 4)
        return 4 if spec is None else spec

    def rowCount(self, parent=None):
        return len(self._df)

    def columnCount(self, parent=None):
        return len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = self._df.iloc[index.row(), index.column()]
            if pd.isna(value):
                return ""
            if isinstance(value, float):
                return f"{value:.{self._decimals_for(index.column())}f}"
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if self._is_numeric_column(index.column()):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.FontRole and self._is_numeric_column(index.column()):
            return QFont("Consolas", 9)
        return None

    def _is_numeric_column(self, col: int) -> bool:
        if self._df.empty:
            return False
        import pandas.api.types as ptypes
        return ptypes.is_numeric_dtype(self._df.dtypes.iloc[col])

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None

        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        else:
            return str(section + 1)

    def set_dataframe(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df
        self.endResetModel()
