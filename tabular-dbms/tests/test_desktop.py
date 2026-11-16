"""Headless Qt + real FastAPI routes through an in-process HTTP transport."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import threading
import httpx
import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from backend.main import create_app
from desktop.api_client import ApiClient, ApiError
from desktop.dialogs import DatabaseDialog, TableDialog, RowDialog
from desktop.workers import TaskRunner
from desktop.window import MainWindow


@pytest.fixture(scope='module')
def qt():
    return QApplication.instance() or QApplication([])


def wait(qt, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        qt.processEvents()
        QTest.qWait(10)
    assert condition(), 'Qt operation timed out'


@pytest.fixture
def api(tmp_path):
    with TestClient(create_app(tmp_path)) as server:
        def handle(request):
            response = server.request(request.method, request.url.path, content=request.content,
                                      headers={'content-type': 'application/json'})
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        yield ApiClient(transport=httpx.MockTransport(handle))


@pytest.mark.parametrize('response,message', [
    (httpx.Response(422,json={'error':{'message':'Неправильне число','field':'age'}}),'age'),
    (httpx.Response(500,text='proxy failed'),'HTTP 500'),
    (httpx.Response(200,text='not json'),'JSON'),
])
def test_client_errors(response,message):
    client=ApiClient(transport=httpx.MockTransport(lambda r: response))
    with pytest.raises(ApiError,match=message):
        client.create_database('Demo')


@pytest.mark.parametrize('exception',[httpx.ReadTimeout, httpx.ConnectError])
def test_uncertain_mutation(exception):
    def fail(request):
        raise exception('offline',request=request)
    client=ApiClient(transport=httpx.MockTransport(fail))
    with pytest.raises(ApiError) as info:
        client.create_database('Demo')
    assert info.value.uncertain
    with pytest.raises(ApiError) as info:
        client.list_databases()
    assert not info.value.uncertain


def test_worker_thread_and_duplicate_submission(qt):
    runner=TaskRunner()
    gate=threading.Event()
    results=[]
    def operation():
        assert QThread.currentThread() != qt.thread()
        gate.wait(2)
        return 42
    def success(result):
        assert QThread.currentThread() == qt.thread()
        results.append(result)
    runner.start(operation, success, lambda e: pytest.fail(str(e)))
    runner.start(lambda: 999, success, lambda e: None)
    qt.processEvents()
    assert runner.busy and results == []
    gate.set()
    wait(qt,lambda:not runner.busy)
    assert results == [42]


def test_dialog_validation_retains_values_and_end_to_end(qt,api):
    dialog=DatabaseDialog(api.create_database)
    dialog.name.setText('Desktop demo')
    dialog.send()
    wait(qt,lambda:not dialog.runner.busy)
    db=dialog.result_data['id']
    table_dialog=TableDialog(lambda data:api.create_table(db,**data))
    table_dialog.name.setText('Samples')
    kinds=['integer','real','char','string','color','colorInvl']
    names=['number','score','mark','title','shade','range']
    for i,kind in enumerate(kinds):
        if i: table_dialog.add_column()
        table_dialog.columns.cellWidget(i,0).setText(names[i])
        table_dialog.columns.cellWidget(i,1).setCurrentText(kind)
    table_dialog.send()
    wait(qt,lambda:not table_dialog.runner.busy)
    table=table_dialog.result_data
    values={'number':10**80,'score':95.5,'mark':'A','title':'',
            'shade':{'red':255,'green':0,'blue':0},
            'range':{'start':{'red':0,'green':0,'blue':0},'end':{'red':100,'green':150,'blue':200}}}
    editor=RowDialog(table['columns'],lambda v:api.add_row(db,table['id'],v), values)
    payload=editor.payload()
    assert payload['number']==str(10**80)
    assert payload['title']==''
    assert payload['range']==values['range']
    score_widget=editor.fields['score'].__self__
    score_widget.setText('wrong')
    editor.send()
    wait(qt,lambda:not editor.runner.busy)
    assert editor.result_data is None and editor.error.text()
    assert editor.payload()['score']=='wrong'
    assert api.get_table(db,table['id'])['rows']==[]
    score_widget.setText('95.5')
    editor.send()
    wait(qt,lambda:not editor.runner.busy)
    row=editor.result_data
    api.add_row(db,table['id'],values)
    assert api.remove_duplicates(db,table['id'])=={'removed':1,'remaining_rows':1}
    api.update_row(db,table['id'],row['id'],{'score':97.5})
    exported=api.export_database(db)
    copied=api.import_database(exported)
    assert copied['id']!=db
    assert api.get_table(copied['id'],table['id'])['rows'][0]['values']['score']==97.5
    assert api.delete_table(copied['id'],table['id']) is None
    assert api.get_database(copied['id'])['tables']==[]
    for widget in (dialog,table_dialog,editor): widget.deleteLater()


def test_uncertain_dialog_prevents_resubmit(qt):
    def fail(value):
        raise ApiError('Timeout',uncertain=True)
    dialog=DatabaseDialog(fail)
    dialog.name.setText('Keep me')
    dialog.send()
    wait(qt,lambda:not dialog.runner.busy)
    assert dialog.uncertain and not dialog.save.isEnabled()
    assert dialog.name.text()=='Keep me'
    dialog.deleteLater()


def test_window_refresh_selection_uuid_and_cleared_deleted_table(qt,api):
    db=api.create_database('Example')
    table=api.create_table(db['id'],'People',[{'name':'name','type':'string'}])
    row=api.add_row(db['id'],table['id'],{'name':'Anna'})
    window=MainWindow(api)
    wait(qt,lambda:window.databases.count()==2 and not window.runner.busy)
    window.databases.setCurrentIndex(1)
    wait(qt,lambda:window.tables.count()==1 and not window.runner.busy)
    window.tables.setCurrentRow(0)
    wait(qt,lambda:window.grid.rowCount()==1 and not window.runner.busy)
    window.grid.selectRow(0)
    assert window.selected_row()['id']==row['id']
    api.delete_table(db['id'],table['id'])
    window.refresh()
    wait(qt,lambda:not window.runner.busy)
    assert window.table is None and window.table_id is None
    assert window.grid.rowCount()==0 and not window.add_button.isEnabled()
    window.close()
    window.deleteLater()
