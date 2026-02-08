"""
TapeCalc - A tape-style calculator for Windows 11
Supports arithmetic, percentage, memory, and Cost/Sell/Markup calculations.
"""

import sys
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QTextEdit, QFileDialog,
    QFrame, QSizePolicy, QDialog, QLineEdit, QFormLayout, QDialogButtonBox,
    QMessageBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QTextCursor, QAction, QKeySequence


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def d(value):
    """Convert to Decimal, stripping commas."""
    if isinstance(value, Decimal):
        return value
    s = str(value).replace(",", "").strip()
    return Decimal(s)


def fmt(value):
    """Format a Decimal for display (up to 10 decimal places, strip trailing zeros)."""
    v = d(value).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    # Use fixed-point notation (avoid scientific like 0E-10)
    s = format(v, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    # Add thousand separators
    parts = s.split(".")
    integer_part = parts[0]
    negative = integer_part.startswith("-")
    if negative:
        integer_part = integer_part[1:]
    groups = []
    while integer_part:
        groups.append(integer_part[-3:])
        integer_part = integer_part[:-3]
    integer_part = ",".join(reversed(groups)) if groups else "0"
    if negative:
        integer_part = "-" + integer_part
    if len(parts) == 2:
        return integer_part + "." + parts[1]
    return integer_part


# ---------------------------------------------------------------------------
# Tape Line data model
# ---------------------------------------------------------------------------

class TapeLine:
    """One line on the tape."""
    def __init__(self, operator="", value=None, label="", is_result=False):
        self.operator = operator      # "+", "-", "×", "÷", "%", "=", ""
        self.value = d(value) if value is not None else Decimal("0")
        self.label = label            # e.g. "total", "Cash Discount", "subtotal"
        self.is_result = is_result    # True for total / subtotal lines

    def to_display(self):
        """Return the string shown on the tape."""
        op = self.operator if self.operator else " "
        val = fmt(self.value)
        lbl = f"  {self.label}" if self.label else ""
        if self.is_result:
            return f"  {val}  {self.label}"
        return f"{op}  {val}{lbl}"

    def to_text(self):
        """Plain-text version for saving."""
        return self.to_display()


# ---------------------------------------------------------------------------
# Calculator Engine
# ---------------------------------------------------------------------------

class CalcEngine:
    def __init__(self):
        self.reset()

    def reset(self):
        self.tape_lines: list[TapeLine] = []
        self.current_input = ""
        self.accumulator = Decimal("0")
        self.pending_op = None
        self.last_value = Decimal("0")
        self.memory = Decimal("0")
        self.has_started = False
        self.last_was_equals = False

    def _apply_op(self, op, a, b):
        if op == "+":
            return a + b
        elif op == "-":
            return a - b
        elif op == "×" or op == "*":
            return a * b
        elif op == "÷" or op == "/":
            if b == 0:
                return Decimal("0")  # guard division by zero
            return a / b
        return b

    def input_digit(self, ch):
        """Handle digit or decimal point input."""
        if self.last_was_equals:
            self.reset()
            self.last_was_equals = False
        if ch == "." and "." in self.current_input:
            return
        self.current_input += ch

    def get_display_value(self):
        if self.current_input:
            try:
                return d(self.current_input)
            except InvalidOperation:
                return self.last_value
        return self.last_value

    def input_operator(self, op):
        """Handle +, -, ×, ÷ operators."""
        self.last_was_equals = False
        val = self.get_display_value()

        if not self.has_started:
            # First number
            self.tape_lines.append(TapeLine("", val))
            self.accumulator = val
            self.has_started = True
        else:
            if self.current_input:
                self.tape_lines.append(TapeLine(self.pending_op or "+", val))
                if self.pending_op:
                    self.accumulator = self._apply_op(self.pending_op, self.accumulator, val)
                else:
                    self.accumulator = val
            # If no current input, just change the pending operator

        self.pending_op = op
        self.last_value = self.accumulator  # Show running total
        self.current_input = ""

    def input_equals(self):
        """Handle = (show total)."""
        val = self.get_display_value()

        if not self.has_started:
            self.tape_lines.append(TapeLine("", val))
            self.accumulator = val
            self.has_started = True
        else:
            if self.current_input:
                self.tape_lines.append(TapeLine(self.pending_op or "+", val))
                if self.pending_op:
                    self.accumulator = self._apply_op(self.pending_op, self.accumulator, val)
                self.pending_op = None

        self.tape_lines.append(TapeLine("", self.accumulator, "total", is_result=True))
        self.last_value = self.accumulator
        self.current_input = ""
        self.has_started = False
        self.pending_op = None
        self.last_was_equals = True

    def input_percent(self):
        """Handle % — computes percentage of the accumulator."""
        val = self.get_display_value()
        if not self.has_started:
            return
        pct_value = self.accumulator * val / Decimal("100")
        # Show on tape as percentage
        self.tape_lines.append(TapeLine("", val, "%"))
        self.tape_lines.append(TapeLine(self.pending_op or "+", pct_value))
        if self.pending_op:
            self.accumulator = self._apply_op(self.pending_op, self.accumulator, pct_value)
        self.current_input = ""
        self.last_value = pct_value
        self.pending_op = None

    def input_backspace(self):
        if self.current_input:
            self.current_input = self.current_input[:-1]

    def input_sign_toggle(self):
        if self.current_input:
            if self.current_input.startswith("-"):
                self.current_input = self.current_input[1:]
            else:
                self.current_input = "-" + self.current_input
        else:
            self.last_value = -self.last_value

    def memory_add(self):
        self.memory += self.get_display_value()
        self.current_input = ""

    def memory_subtract(self):
        self.memory -= self.get_display_value()
        self.current_input = ""

    def memory_recall(self):
        val = self.memory
        self.current_input = str(val)
        self.last_value = val

    def memory_clear(self):
        self.memory = Decimal("0")

    def recalculate_from_tape(self, tape_lines):
        """Recalculate totals from edited tape lines."""
        recalculated = []
        acc = Decimal("0")
        first = True
        for line in tape_lines:
            if line.is_result:
                recalculated.append(TapeLine("", acc, line.label, is_result=True))
                first = True
                continue
            if first:
                acc = line.value
                first = False
            else:
                op = line.operator if line.operator else "+"
                acc = self._apply_op(op, acc, line.value)
            recalculated.append(TapeLine(line.operator, line.value, line.label, line.is_result))

        self.tape_lines = recalculated
        self.accumulator = acc
        self.last_value = acc
        return recalculated


# ---------------------------------------------------------------------------
# Cost / Sell / Markup Dialog
# ---------------------------------------------------------------------------

class MarkupDialog(QDialog):
    """Dialog for computing Cost / Sell / Markup.

    Given any two of three values, compute the third:
      Sell = Cost + (Cost × Markup%)
      Markup% = ((Sell - Cost) / Cost) × 100
      Cost = Sell / (1 + Markup% / 100)
    """

    def __init__(self, parent=None, initial_value=None):
        super().__init__(parent)
        self.setWindowTitle("Cost / Sell / Markup")
        self.setMinimumWidth(320)
        self.result_value = None
        self.result_label = ""

        layout = QVBoxLayout(self)

        info = QLabel("Enter any two values to compute the third.\n"
                       "Leave one field empty to calculate it.")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.cost_edit = QLineEdit()
        self.sell_edit = QLineEdit()
        self.markup_edit = QLineEdit()

        self.cost_edit.setPlaceholderText("e.g. 100.00")
        self.sell_edit.setPlaceholderText("e.g. 150.00")
        self.markup_edit.setPlaceholderText("e.g. 50")

        # Pre-fill cost with current calculator value if available
        if initial_value is not None:
            self.cost_edit.setText(fmt(initial_value))

        form.addRow("Cost:", self.cost_edit)
        form.addRow("Sell:", self.sell_edit)
        form.addRow("Markup %:", self.markup_edit)
        layout.addLayout(form)

        self.result_label_widget = QLabel("")
        self.result_label_widget.setStyleSheet("font-weight: bold; color: #2a5a2a; font-size: 14px;")
        layout.addWidget(self.result_label_widget)

        btn_layout = QHBoxLayout()
        calc_btn = QPushButton("Calculate")
        calc_btn.clicked.connect(self.calculate)
        calc_btn.setDefault(True)

        send_cost_btn = QPushButton("Send Cost to Tape")
        send_cost_btn.clicked.connect(lambda: self.send_to_tape("cost"))
        send_sell_btn = QPushButton("Send Sell to Tape")
        send_sell_btn.clicked.connect(lambda: self.send_to_tape("sell"))

        btn_layout.addWidget(calc_btn)
        btn_layout.addWidget(send_cost_btn)
        btn_layout.addWidget(send_sell_btn)
        layout.addLayout(btn_layout)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

        # Style
        self.setStyleSheet("""
            QDialog { background: #f5f5f0; }
            QLineEdit { padding: 6px; font-size: 14px; border: 1px solid #ccc; border-radius: 3px; }
            QPushButton { padding: 8px 14px; font-size: 13px; background: #4a7a4a; color: white;
                          border: none; border-radius: 4px; }
            QPushButton:hover { background: #3a6a3a; }
        """)

    def calculate(self):
        cost_text = self.cost_edit.text().replace(",", "").strip()
        sell_text = self.sell_edit.text().replace(",", "").strip()
        markup_text = self.markup_edit.text().replace(",", "").replace("%", "").strip()

        cost = d(cost_text) if cost_text else None
        sell = d(sell_text) if sell_text else None
        markup = d(markup_text) if markup_text else None

        filled = sum(1 for v in [cost, sell, markup] if v is not None)
        if filled < 2:
            self.result_label_widget.setText("Please fill in at least two fields.")
            return

        try:
            if cost is None:
                # Cost = Sell / (1 + Markup/100)
                cost = sell / (1 + markup / 100)
                self.cost_edit.setText(fmt(cost))
                self.result_label_widget.setText(f"Cost = {fmt(cost)}")
            elif sell is None:
                # Sell = Cost × (1 + Markup/100)
                sell = cost * (1 + markup / 100)
                self.sell_edit.setText(fmt(sell))
                self.result_label_widget.setText(f"Sell = {fmt(sell)}")
            elif markup is None:
                # Markup% = ((Sell - Cost) / Cost) × 100
                if cost == 0:
                    self.result_label_widget.setText("Cost cannot be zero for markup calc.")
                    return
                markup = ((sell - cost) / cost) * 100
                self.markup_edit.setText(fmt(markup))
                self.result_label_widget.setText(f"Markup = {fmt(markup)}%")
            else:
                # All three filled — verify
                expected_sell = cost * (1 + markup / 100)
                diff = abs(expected_sell - sell)
                if diff < Decimal("0.02"):
                    self.result_label_widget.setText("All values are consistent ✓")
                else:
                    self.result_label_widget.setText(
                        f"Inconsistent! Expected Sell = {fmt(expected_sell)}")
        except Exception as e:
            self.result_label_widget.setText(f"Error: {e}")

    def send_to_tape(self, which):
        text = ""
        label = ""
        if which == "cost":
            text = self.cost_edit.text().replace(",", "").strip()
            label = "Cost"
        elif which == "sell":
            text = self.sell_edit.text().replace(",", "").strip()
            label = "Sell"
        if text:
            try:
                self.result_value = d(text)
                self.result_label = label
                self.accept()
            except InvalidOperation:
                self.result_label_widget.setText("Invalid number")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class TapeCalcWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = CalcEngine()
        self.setWindowTitle("TapeCalc")
        self.setMinimumSize(380, 620)
        self.resize(400, 700)
        self._build_ui()
        self._update_display()

    # ---- UI Construction ----

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- Keyboard shortcuts (no menu bar) ----
        save_action = QAction(self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.save_tape)
        self.addAction(save_action)

        markup_action = QAction(self)
        markup_action.setShortcut(QKeySequence("Ctrl+M"))
        markup_action.triggered.connect(self.open_markup_dialog)
        self.addAction(markup_action)

        # ---- Title bar area ----
        title_bar = QFrame()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet("background-color: #7a8a6a; padding-left: 10px;")
        title_label = QLabel("TapeCalc")
        title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title_label.setStyleSheet("color: white;")
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(10, 0, 10, 0)
        tl.addWidget(title_label)
        tl.addStretch()
        main_layout.addWidget(title_bar)

        # ---- Tape area (editable) ----
        self.tape_edit = QTextEdit()
        self.tape_edit.setFont(QFont("Consolas", 12))
        self.tape_edit.setStyleSheet("""
            QTextEdit {
                background-color: #fffde0;
                border: none;
                padding: 8px;
                color: #333;
                selection-background-color: #c8dbb8;
            }
        """)
        self.tape_edit.setMinimumHeight(180)
        self.tape_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tape_edit.textChanged.connect(self._on_tape_edited)
        self._tape_updating = False  # Guard against recursive updates
        main_layout.addWidget(self.tape_edit, stretch=3)

        # ---- Separator ----
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background-color: #bbb;")
        main_layout.addWidget(sep)

        # ---- Display area ----
        display_frame = QFrame()
        display_frame.setFixedHeight(56)
        display_frame.setStyleSheet("background-color: #d4e4c0; border: none;")
        dl = QHBoxLayout(display_frame)
        dl.setContentsMargins(12, 4, 12, 4)

        self.display_label = QLabel("0")
        self.display_label.setFont(QFont("Consolas", 22, QFont.Weight.Bold))
        self.display_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.display_label.setStyleSheet("color: #1a1a1a; background: transparent;")
        dl.addWidget(self.display_label)
        main_layout.addWidget(display_frame)

        # ---- Button grid ----
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background-color: #e8e8e0;")
        grid = QGridLayout(btn_frame)
        grid.setSpacing(3)
        grid.setContentsMargins(4, 4, 4, 4)

        # Row 0: AC, ⌫, MR, CSM (Cost/Sell/Markup)
        self._add_btn(grid, "AC",  0, 0, "#d94040", "white", self._on_ac)
        self._add_btn(grid, "⌫",   0, 1, "#d97040", "white", self._on_backspace)
        self._add_btn(grid, "MR",  0, 2, "#5a8a5a", "white", lambda: self.engine.memory_recall() or self._update_display())
        self._add_btn(grid, "CSM", 0, 3, "#5a6a8a", "white", self.open_markup_dialog)

        # Row 1: M+, M-, MC, +
        self._add_btn(grid, "M+",  1, 0, "#6a7a6a", "white", lambda: self.engine.memory_add() or self._update_display())
        self._add_btn(grid, "M−",  1, 1, "#6a7a6a", "white", lambda: self.engine.memory_subtract() or self._update_display())
        self._add_btn(grid, "MC",  1, 2, "#6a7a6a", "white", lambda: self.engine.memory_clear() or self._update_display())
        self._add_btn(grid, "+",   1, 3, "#5a8a5a", "white", lambda: self._on_operator("+"))

        # Row 2: 7, 8, 9, -
        self._add_btn(grid, "7", 2, 0, "#fafafa", "#222", lambda: self._on_digit("7"))
        self._add_btn(grid, "8", 2, 1, "#fafafa", "#222", lambda: self._on_digit("8"))
        self._add_btn(grid, "9", 2, 2, "#fafafa", "#222", lambda: self._on_digit("9"))
        self._add_btn(grid, "−", 2, 3, "#5a8a5a", "white", lambda: self._on_operator("-"))

        # Row 3: 4, 5, 6, ×
        self._add_btn(grid, "4", 3, 0, "#fafafa", "#222", lambda: self._on_digit("4"))
        self._add_btn(grid, "5", 3, 1, "#fafafa", "#222", lambda: self._on_digit("5"))
        self._add_btn(grid, "6", 3, 2, "#fafafa", "#222", lambda: self._on_digit("6"))
        self._add_btn(grid, "×", 3, 3, "#5a8a5a", "white", lambda: self._on_operator("×"))

        # Row 4: 1, 2, 3, ÷
        self._add_btn(grid, "1", 4, 0, "#fafafa", "#222", lambda: self._on_digit("1"))
        self._add_btn(grid, "2", 4, 1, "#fafafa", "#222", lambda: self._on_digit("2"))
        self._add_btn(grid, "3", 4, 2, "#fafafa", "#222", lambda: self._on_digit("3"))
        self._add_btn(grid, "÷", 4, 3, "#5a8a5a", "white", lambda: self._on_operator("÷"))

        # Row 5: 0, ., =, %
        self._add_btn(grid, "0", 5, 0, "#fafafa", "#222", lambda: self._on_digit("0"))
        self._add_btn(grid, ".", 5, 1, "#fafafa", "#222", lambda: self._on_digit("."))
        self._add_btn(grid, "=", 5, 2, "#5a8a5a", "white", self._on_equals)
        self._add_btn(grid, "%", 5, 3, "#5a8a5a", "white", self._on_percent)

        # Row 6: ±, Save
        self._add_btn(grid, "±",    6, 0, "#6a7a6a", "white", self._on_sign_toggle)
        self._add_btn(grid, "Save", 6, 1, "#5a6a8a", "white", self.save_tape, colspan=2)
        # leave 6,3 empty or add something

        main_layout.addWidget(btn_frame, stretch=0)

        # ---- Status bar ----
        self.statusBar().showMessage("Ready")
        self.statusBar().setStyleSheet("background: #e0e0d8; color: #555; font-size: 11px;")

    def _add_btn(self, grid, text, row, col, bg, fg, callback, colspan=1):
        btn = QPushButton(text)
        btn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        btn.setMinimumSize(QSize(70, 48))
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1px solid #bbb;
                border-radius: 4px;
                padding: 6px;
            }}
            QPushButton:hover {{
                border: 2px solid #888;
            }}
            QPushButton:pressed {{
                background-color: #aaa;
            }}
        """)
        btn.clicked.connect(callback)
        grid.addWidget(btn, row, col, 1, colspan)
        return btn

    # ---- Keyboard support ----

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()

        # Don't intercept keys when tape editor has focus
        if self.tape_edit.hasFocus():
            super().keyPressEvent(event)
            return

        if text in "0123456789.":
            self._on_digit(text)
        elif text == "+" or key == Qt.Key.Key_Plus:
            self._on_operator("+")
        elif text == "-" or key == Qt.Key.Key_Minus:
            self._on_operator("-")
        elif text == "*":
            self._on_operator("×")
        elif text == "/":
            self._on_operator("÷")
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._on_equals()
        elif key == Qt.Key.Key_Percent:
            self._on_percent()
        elif key == Qt.Key.Key_Backspace:
            self._on_backspace()
        elif key == Qt.Key.Key_Escape:
            self._on_ac()
        elif key == Qt.Key.Key_Delete:
            self._on_ac()
        else:
            super().keyPressEvent(event)

    # ---- Button handlers ----

    def _on_digit(self, ch):
        self.engine.input_digit(ch)
        self._update_display()

    def _on_operator(self, op):
        self.engine.input_operator(op)
        self._update_display()
        self._update_tape()

    def _on_equals(self):
        self.engine.input_equals()
        self._update_display()
        self._update_tape()

    def _on_percent(self):
        self.engine.input_percent()
        self._update_display()
        self._update_tape()

    def _on_backspace(self):
        self.engine.input_backspace()
        self._update_display()

    def _on_ac(self):
        self.engine.reset()
        self._update_display()
        self._tape_updating = True
        self.tape_edit.clear()
        self._tape_updating = False
        self.statusBar().showMessage("Cleared")

    def _on_sign_toggle(self):
        self.engine.input_sign_toggle()
        self._update_display()

    # ---- Display / Tape sync ----

    def _update_display(self):
        val = self.engine.get_display_value()
        if self.engine.current_input:
            self.display_label.setText(self.engine.current_input)
        else:
            self.display_label.setText(fmt(val))

    def _update_tape(self):
        """Rebuild the tape text from the engine's tape_lines."""
        self._tape_updating = True
        lines = []
        for tl in self.engine.tape_lines:
            if tl.is_result:
                lines.append(f"  {fmt(tl.value)}  {tl.label}")
            else:
                op = tl.operator if tl.operator else " "
                lbl = f"  {tl.label}" if tl.label else ""
                lines.append(f"{op}  {fmt(tl.value)}{lbl}")
        self.tape_edit.setPlainText("\n".join(lines))
        # Scroll to bottom
        cursor = self.tape_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.tape_edit.setTextCursor(cursor)
        self._tape_updating = False

    def _on_tape_edited(self):
        """When the user manually edits the tape, parse and recalculate."""
        if self._tape_updating:
            return
        text = self.tape_edit.toPlainText()
        lines = text.split("\n")
        parsed = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Try to parse: [operator] [number] [label]
            # Result lines have format: "  number  label"
            # Regular lines have format: "op  number  label"
            m = re.match(
                r'^([+\-×÷*/])?\s*(-?[\d,]+\.?\d*)\s*(.*)$', line
            )
            if m:
                op = m.group(1) or ""
                try:
                    val = d(m.group(2))
                except InvalidOperation:
                    continue
                label = m.group(3).strip()
                is_result = label in ("total", "subtotal", "Total", "Subtotal")
                if op == "*":
                    op = "×"
                elif op == "/":
                    op = "÷"
                parsed.append(TapeLine(op, val, label, is_result))
        if parsed:
            recalculated = self.engine.recalculate_from_tape(parsed)
            self._update_display()
            self.statusBar().showMessage("Tape recalculated")

    # ---- Save ----

    def save_tape(self):
        text = self.tape_edit.toPlainText()
        if not text.strip():
            self.statusBar().showMessage("Nothing to save")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Tape", "tape.txt", "Text Files (*.txt);;All Files (*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("TapeCalc — Tape Output\n")
                    f.write("=" * 40 + "\n")
                    f.write(text)
                    f.write("\n" + "=" * 40 + "\n")
                self.statusBar().showMessage(f"Saved to {path}")
            except OSError as e:
                QMessageBox.warning(self, "Save Error", str(e))

    # ---- Cost/Sell/Markup ----

    def open_markup_dialog(self):
        val = self.engine.get_display_value()
        dlg = MarkupDialog(self, initial_value=val if val != 0 else None)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_value is not None:
            # Send the result value to the tape as a new entry
            self.engine.current_input = str(dlg.result_value)
            self.engine.last_was_equals = False
            self._update_display()
            self.statusBar().showMessage(f"{dlg.result_label}: {fmt(dlg.result_value)} sent to calculator")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Global stylesheet for a clean Windows 11 look
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f0f0e8;
        }
    """)

    window = TapeCalcWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
