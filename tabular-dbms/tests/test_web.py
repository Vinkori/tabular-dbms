"""HTTP delivery of the web client without weakening the API contract."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app


def test_index_assets_and_api_together(tmp_path):
    with TestClient(create_app(tmp_path / 'storage')) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert page.headers['content-type'].startswith('text/html')
        assert page.headers['cache-control'] == 'no-cache'
        assert '<html lang="uk">' in page.text
        assert '/static/app.js' in page.text and '/static/style.css' in page.text
        assert 'editor-form' in page.text
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get('/docs').status_code == 200
        assert client.get('/api/databases').json() == []
        css = client.get('/static/style.css')
        script = client.get('/static/app.js')
        assert css.status_code == script.status_code == 200
        assert css.headers['content-type'].startswith('text/css')
        assert 'javascript' in script.headers['content-type']
        assert '#f8dfcb' in css.text and '#b94f20' in css.text


def test_web_paths_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(tmp_path / 'data')) as client:
        assert client.get('/').status_code == 200
        assert client.get('/static/app.js').status_code == 200


@pytest.mark.parametrize('path', ['/static/missing.css', '/not-a-route', '/static/%2e%2e/repository.py'])
def test_missing_static_and_routes_return_json_error(tmp_path, path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'NOT_FOUND'
