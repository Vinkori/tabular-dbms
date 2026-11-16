import json
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QComboBox, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QFileDialog, QMessageBox)
from desktop.api_client import ApiClient
from desktop.dialogs import DatabaseDialog, TableDialog, RowDialog, label
from desktop.workers import TaskRunner


def display_value(value):
    if isinstance(value, dict) and 'red' in value:
        return f"RGB({value['red']}, {value['green']}, {value['blue']})"
    if isinstance(value, dict) and 'start' in value:
        return display_value(value['start']) + ' → ' + display_value(value['end'])
    return str(value)


class MainWindow(QMainWindow):
    def __init__(self, api=None):
        super().__init__()
        self.api = api or ApiClient()
        self.runner = TaskRunner(self)
        self.db_id = self.table_id = None
        self.table = None
        self.uncertain = False
        self.mutations = []
        self.setWindowTitle('Таблична · робочий журнал')
        self.resize(1320, 760)
        self.setMinimumSize(940, 600)
        self.root = QWidget()
        self.setCentralWidget(self.root)
        outer = QHBoxLayout(self.root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        side = QWidget()
        side.setObjectName('sidebar')
        side.setFixedWidth(270)
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(20, 26, 20, 20)
        brand = label('Таблична.')
        brand.setObjectName('brand')
        sidebar.addWidget(brand)
        subtitle = label('РОБОЧИЙ ЖУРНАЛ / 01')
        subtitle.setObjectName('muted')
        sidebar.addWidget(subtitle)
        sidebar.addSpacing(25)
        sidebar.addWidget(label('БАЗА ДАНИХ'))
        self.databases = QComboBox()
        self.databases.currentIndexChanged.connect(self.choose_database)
        sidebar.addWidget(self.databases)
        sidebar.addWidget(self.button('+ Нова база', self.new_database, mutation=True))
        sidebar.addSpacing(20)
        sidebar.addWidget(label('ТАБЛИЦІ'))
        self.tables = QListWidget()
        self.tables.currentItemChanged.connect(self.choose_table)
        sidebar.addWidget(self.tables, 1)
        self.new_table_button = self.button('+ Нова таблиця', self.new_table, mutation=True)
        sidebar.addWidget(self.new_table_button)
        sidebar.addWidget(self.button('Імпортувати JSON…', self.import_database, mutation=True))
        self.export_button = self.button('Експортувати базу…', self.export_database)
        sidebar.addWidget(self.export_button)
        outer.addWidget(side)
        main = QWidget()
        content = QVBoxLayout(main)
        content.setContentsMargins(28, 28, 28, 20)
        heading = QHBoxLayout()
        self.title = label('Ваші дані, по порядку')
        self.title.setObjectName('title')
        heading.addWidget(self.title, 1)
        heading.addWidget(self.button('Оновити', self.refresh))
        content.addLayout(heading)
        self.description = label('Створіть базу або виберіть її ліворуч.')
        self.description.setObjectName('muted')
        content.addWidget(self.description)
        content.addSpacing(16)
        actions = QHBoxLayout()
        self.add_button = self.button('+ Додати рядок', self.add_row, mutation=True)
        self.add_button.setObjectName('primary')
        self.edit_button = self.button('Редагувати', self.edit_row, mutation=True)
        self.dedup_button = self.button('Прибрати повтори', self.deduplicate, mutation=True)
        for button in (self.add_button, self.edit_button, self.dedup_button):
            actions.addWidget(button)
        actions.addStretch()
        self.delete_button = self.button('Видалити таблицю', self.delete_table, mutation=True)
        actions.addWidget(self.delete_button)
        content.addLayout(actions)
        self.grid = QTableWidget()
        self.grid.setAlternatingRowColors(True)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setWordWrap(False)
        self.grid.verticalHeader().setDefaultSectionSize(40)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.itemSelectionChanged.connect(self.update_actions)
        self.grid.doubleClicked.connect(self.edit_row)
        content.addWidget(self.grid, 1)
        self.footnote = label('Виберіть таблицю для перегляду. Зміни зберігаються автоматично.')
        self.footnote.setObjectName('muted')
        content.addWidget(self.footnote)
        outer.addWidget(main, 1)
        self.runner.busy_changed.connect(self.busy_changed)
        self.update_actions()
        QTimer.singleShot(0, self.refresh)

    def button(self, text, callback, mutation=False):
        button = QPushButton(text)
        button.clicked.connect(callback)
        if mutation:
            self.mutations.append(button)
        return button

    def busy_changed(self, busy):
        self.root.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage('Очікуємо відповідь сервера…')
        self.update_actions()

    def update_actions(self):
        for button in self.mutations:
            button.setEnabled(not self.uncertain)
        self.new_table_button.setEnabled(bool(self.db_id) and not self.uncertain)
        self.export_button.setEnabled(bool(self.db_id))
        for button in (self.add_button, self.dedup_button, self.delete_button):
            button.setEnabled(self.table is not None and not self.uncertain)
        self.edit_button.setEnabled(self.selected_row() is not None and not self.uncertain)

    def selected_row(self):
        index = self.grid.currentRow()
        if self.table is None or index < 0 or index >= self.grid.rowCount():
            return None
        item = self.grid.item(index, 0)
        row_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((row for row in self.table['rows'] if row['id'] == row_id), None)

    def refresh(self):
        db_id, table_id = self.db_id, self.table_id
        def fetch():
            databases = self.api.list_databases()
            selected = db_id if any(d['id'] == db_id for d in databases) else None
            database = self.api.get_database(selected) if selected else None
            valid = database and any(t['id'] == table_id for t in database['tables'])
            table = self.api.get_table(selected, table_id) if valid else None
            return databases, database, table
        self.runner.start(fetch, self.render, self.failed)

    def render(self, data):
        databases, database, table = data
        self.db_id = database['id'] if database else None
        self.table_id = table['id'] if table else None
        self.table = table
        self.uncertain = False
        self.databases.blockSignals(True)
        self.databases.clear()
        self.databases.addItem('Виберіть базу…', None)
        for db in databases:
            self.databases.addItem(db['name'], db['id'])
            self.databases.setItemData(self.databases.count()-1, db['id'], Qt.ItemDataRole.ToolTipRole)
        self.databases.setCurrentIndex(max(0, self.databases.findData(self.db_id)))
        self.databases.blockSignals(False)
        self.tables.blockSignals(True)
        self.tables.clear()
        for entry in database['tables'] if database else []:
            item = QListWidgetItem(entry['name'])
            item.setData(Qt.ItemDataRole.UserRole, entry['id'])
            self.tables.addItem(item)
            if entry['id'] == self.table_id:
                self.tables.setCurrentItem(item)
        self.tables.blockSignals(False)
        self.grid.clear()
        self.grid.setRowCount(0)
        columns = table['columns'] if table else []
        self.grid.setColumnCount(len(columns))
        self.grid.setHorizontalHeaderLabels([c['name'] + '\n' + c['type'] for c in columns])
        for i, row in enumerate(table['rows'] if table else []):
            self.grid.insertRow(i)
            for j, column in enumerate(columns):
                value = row['values'][column['name']]
                item = QTableWidgetItem(display_value(value))
                item.setData(Qt.ItemDataRole.UserRole, row['id'])
                item.setToolTip(display_value(value))
                if column['type'] == 'color':
                    item.setData(Qt.ItemDataRole.DecorationRole, QColor(value['red'], value['green'], value['blue']))
                self.grid.setItem(i, j, item)
        for j in range(len(columns)):
            widths = {'integer': 100, 'real': 100, 'char': 80, 'string': 150, 'color': 190, 'colorInvl': 330}
            self.grid.setColumnWidth(j, widths[columns[j]['type']])
        self.title.setText(table['name'] if table else 'Ваші дані, по порядку')
        self.description.setText(database['name'] if database else 'Створіть базу або виберіть її ліворуч.')
        self.footnote.setText(f"Рядків: {len(table['rows'])}   /   Колонок: {len(columns)}   ·   Збережено на сервері"
                              if table else 'Виберіть або створіть таблицю ліворуч.')
        self.statusBar().showMessage('Дані оновлено')
        self.update_actions()

    def choose_database(self):
        self.db_id = self.databases.currentData()
        self.table_id = None
        self.refresh()

    def choose_table(self, current, previous):
        self.table_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.refresh()

    def failed(self, error):
        self.uncertain = True
        self.update_actions()
        self.statusBar().showMessage('Потрібно оновити дані')
        box = QMessageBox(self)
        box.setWindowTitle('Не вдалося виконати дію')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(str(error) + '\nНатисніть «Оновити» перед наступною зміною.')
        box.exec()

    def run_dialog(self, dialog, kind=None):
        if dialog.exec():
            if kind == 'database':
                self.db_id, self.table_id = dialog.result_data['id'], None
            elif kind == 'table':
                self.table_id = dialog.result_data['id']
            self.refresh()
        elif dialog.uncertain:
            self.uncertain = True
            self.update_actions()
            self.statusBar().showMessage('Результат запису невідомий. Натисніть «Оновити».')
        dialog.deleteLater()

    def new_database(self):
        self.run_dialog(DatabaseDialog(self.api.create_database, self), 'database')

    def new_table(self):
        db = self.db_id
        self.run_dialog(TableDialog(lambda data: self.api.create_table(db, **data), self), 'table')

    def add_row(self):
        db, table = self.db_id, self.table_id
        self.run_dialog(RowDialog(self.table['columns'], lambda values: self.api.add_row(db, table, values), parent=self))

    def edit_row(self):
        row = self.selected_row()
        if row is None or self.uncertain:
            return
        db, table = self.db_id, self.table_id
        self.run_dialog(RowDialog(self.table['columns'],
            lambda values: self.api.update_row(db, table, row['id'], values), row['values'], self))

    def deduplicate(self):
        def done(result):
            QMessageBox.information(self, 'Повтори вилучено',
                f"Вилучено: {result['removed']}\nЗалишилося рядків: {result['remaining_rows']}")
            self.refresh()
        db, table = self.db_id, self.table_id
        self.runner.start(lambda: self.api.remove_duplicates(db, table), done, self.failed)

    def delete_table(self):
        if QMessageBox.question(self, 'Видалити таблицю?',
                'Таблицю та всі її рядки буде видалено. Продовжити?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        db, table = self.db_id, self.table_id
        def done(result):
            self.table_id = None
            self.refresh()
        self.runner.start(lambda: self.api.delete_table(db, table), done, self.failed)

    def import_database(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Імпортувати базу', '', 'JSON (*.json)')
        if not path:
            return
        def load():
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError(f'Повторний ключ JSON: {key}')
                    result[key] = value
                return result
            def invalid(value):
                raise ValueError('Неприпустиме число JSON: ' + value)
            document = json.loads(Path(path).read_text(encoding='utf-8-sig'),
                                  object_pairs_hook=pairs, parse_constant=invalid)
            return self.api.import_database(document)
        def done(result):
            self.db_id, self.table_id = result['id'], None
            self.refresh()
        self.runner.start(load, done, self.failed)

    def export_database(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Експортувати базу', 'database.json', 'JSON (*.json)')
        if not path:
            return
        db = self.db_id
        def save():
            data = self.api.export_database(db)
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        self.runner.start(save, lambda _: self.statusBar().showMessage('Експорт збережено: ' + path), self.failed)

    def closeEvent(self, event):
        if self.runner.busy:
            self.statusBar().showMessage('Зачекайте завершення поточного запиту.')
            event.ignore()
        else:
            super().closeEvent(event)
