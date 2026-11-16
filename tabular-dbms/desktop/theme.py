"""Shared visual direction for the desktop and the future web client."""
STYLE = '''
QWidget { color: #382b25; font-family: "Segoe UI", "DejaVu Sans"; font-size: 13px; }
QMainWindow, QDialog, QWidget#formBody { background: #fff8f1; }
QWidget#sidebar { background: #f8dfcb; border-right: 1px solid #dfb99b; }
QLabel#brand { font-size: 26px; font-weight: 700; color: #923e1b; }
QLabel#title { font-size: 24px; font-weight: 600; }
QLabel#muted { color: #796558; }
QLabel#error { color: #a02b1d; padding: 8px; }
QPushButton { background: #fffaf5; border: 1px solid #cbaa91; padding: 8px 12px; border-radius: 4px; }
QPushButton:hover { background: #f9dcc4; border-color: #b85b2d; }
QPushButton:pressed { background: #efc39f; }
QPushButton#primary { background: #b94f20; color: white; border-color: #b94f20; }
QPushButton#primary:hover { background: #963b16; }
QPushButton:disabled { color: #a39386; background: #eee5dc; border-color: #ddd0c4; }
QLineEdit, QSpinBox, QComboBox { background: #fffdf9; border: 1px solid #cbaa91; padding: 7px; border-radius: 3px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #b94f20; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 10px; border-bottom: 1px solid #e5c6ad; }
QListWidget::item:selected { background: #edbc96; color: #572b17; }
QTableWidget { background: #fffdf9; alternate-background-color: #fcf1e6; gridline-color: #ead8c8; border: 1px solid #dfc4ae; selection-background-color: #f5cfac; selection-color: #382b25; }
QHeaderView::section { background: #f6e3d2; color: #643f2b; padding: 10px; border: none; border-bottom: 1px solid #d9b99f; font-weight: 600; }
QStatusBar { background: #f8dfcb; border-top: 1px solid #dfb99b; }
QScrollArea { border: none; background: transparent; }
'''
