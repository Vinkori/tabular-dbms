from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QWidget,
    QScrollArea, QTableWidget, QHeaderView)
from desktop.workers import TaskRunner

TYPES = ('integer', 'real', 'char', 'string', 'color', 'colorInvl')


def label(text):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class SubmitDialog(QDialog):
    def __init__(self, title, submit, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(590, 430)
        self.submit = submit
        self.result_data = None
        self.uncertain = False
        self.runner = TaskRunner(self)
        self.layout = QVBoxLayout(self)
        self.error = label('')
        self.error.setObjectName('error')
        self.save = QPushButton('Зберегти')
        self.save.setObjectName('primary')
        self.cancel = QPushButton('Скасувати')
        self.save.clicked.connect(self.send)
        self.cancel.clicked.connect(self.reject)
        self.runner.busy_changed.connect(self.set_busy)

    def finish_layout(self):
        self.layout.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.save)
        self.layout.addLayout(buttons)

    def set_busy(self, busy):
        self.save.setEnabled(not busy and not self.uncertain)
        self.cancel.setEnabled(not busy)
        self.save.setText('Збереження…' if busy else 'Зберегти')

    def send(self):
        try:
            payload = self.payload()
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.error.setText('')
        self.runner.start(lambda: self.submit(payload), self.saved, self.failed)

    def saved(self, result):
        self.result_data = result
        self.accept()

    def failed(self, error):
        self.uncertain = getattr(error, 'uncertain', False)
        self.error.setText(str(error) + (' Закрийте форму та натисніть «Оновити».' if self.uncertain else ''))
        self.set_busy(False)

    def reject(self):
        if not self.runner.busy:
            super().reject()

    def closeEvent(self, event):
        if self.runner.busy:
            event.ignore()
        else:
            super().closeEvent(event)


class DatabaseDialog(SubmitDialog):
    def __init__(self, submit, parent=None):
        super().__init__('Нова база', submit, parent)
        self.name = QLineEdit()
        self.name.setPlaceholderText('Наприклад, Навчальна колекція')
        self.layout.addWidget(label('Назва бази'))
        self.layout.addWidget(self.name)
        self.layout.addStretch()
        self.finish_layout()

    def payload(self):
        return self.name.text()


class TableDialog(SubmitDialog):
    def __init__(self, submit, parent=None):
        super().__init__('Нова таблиця', submit, parent)
        self.name = QLineEdit()
        self.layout.addWidget(label('Назва таблиці'))
        self.layout.addWidget(self.name)
        self.columns = QTableWidget(0, 2)
        self.columns.setHorizontalHeaderLabels(['Назва колонки', 'Тип'])
        self.columns.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.layout.addWidget(self.columns)
        actions = QHBoxLayout()
        add = QPushButton('+ Колонка')
        remove = QPushButton('Прибрати вибрану колонку')
        add.clicked.connect(self.add_column)
        remove.clicked.connect(lambda: self.columns.removeRow(self.columns.currentRow()))
        actions.addWidget(add)
        actions.addWidget(remove)
        self.layout.addLayout(actions)
        self.add_column()
        self.finish_layout()

    def add_column(self):
        row = self.columns.rowCount()
        self.columns.insertRow(row)
        self.columns.setCellWidget(row, 0, QLineEdit())
        kind = QComboBox()
        kind.addItems(TYPES)
        self.columns.setCellWidget(row, 1, kind)

    def payload(self):
        return {'name': self.name.text(), 'columns': [
            {'name': self.columns.cellWidget(i, 0).text(),
             'type': self.columns.cellWidget(i, 1).currentText()}
            for i in range(self.columns.rowCount())]}


class RGBEditor(QWidget):
    def __init__(self, value=None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.channels = {}
        for key, caption in [('red', 'R'), ('green', 'G'), ('blue', 'B')]:
            layout.addWidget(label(caption))
            field = QSpinBox()
            field.setRange(0, 255)
            field.setValue((value or {}).get(key, 0))
            layout.addWidget(field)
            self.channels[key] = field

    def value(self):
        return {key: widget.value() for key, widget in self.channels.items()}


class RowDialog(SubmitDialog):
    def __init__(self, columns, submit, values=None, parent=None):
        super().__init__('Редагувати рядок' if values is not None else 'Додати рядок', submit, parent)
        self.resize(650, 550)
        self.fields = {}
        body = QWidget()
        body.setObjectName("formBody")
        form = QFormLayout(body)
        for column in columns:
            name, kind = column['name'], column['type']
            value = (values or {}).get(name)
            if kind == 'color':
                field = RGBEditor(value)
                getter = field.value
            elif kind == 'colorInvl':
                field = QWidget()
                inner = QFormLayout(field)
                inner.setContentsMargins(0, 0, 0, 0)
                start = RGBEditor(value['start'] if value else None)
                end = RGBEditor(value['end'] if value else None)
                inner.addRow('Від', start)
                inner.addRow('До', end)
                getter = lambda a=start, b=end: {'start': a.value(), 'end': b.value()}
            else:
                field = QLineEdit('' if value is None else str(value))
                if kind in ('integer', 'real'):
                    field.setPlaceholderText('Ціле число' if kind == 'integer' else 'Число, наприклад 95.5')
                getter = field.text
            form.addRow(label(f'{name} · {kind}'), field)
            self.fields[name] = getter
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.layout.addWidget(scroll)
        self.finish_layout()

    def payload(self):
        return {name: getter() for name, getter in self.fields.items()}
