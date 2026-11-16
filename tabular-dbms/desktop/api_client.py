"""HTTP boundary. Desktop never reads the server's storage."""
import httpx


class ApiError(Exception):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class ApiClient:
    def __init__(self, base_url='http://127.0.0.1:8000', timeout=10.0, transport=None):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.transport = transport

    def request(self, method, path, data=None):
        mutation = method not in ('GET', 'HEAD')
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout,
                              transport=self.transport, trust_env=False) as client:
                response = client.request(method, '/api' + path, json=data)
        except httpx.TimeoutException as error:
            raise ApiError('Сервер не відповів вчасно. Оновіть дані перед повторенням дії.',
                           uncertain=mutation) from error
        except httpx.RequestError as error:
            raise ApiError('Немає зв’язку із сервером. Перевірте його запуск і оновіть дані.',
                           uncertain=mutation) from error
        if not response.is_success:
            message = f'Сервер повернув HTTP {response.status_code}.'
            try:
                detail = response.json()['error']
                message = str(detail['message'])
                if detail.get('field'):
                    message += f" (поле: {detail['field']})"
            except (ValueError, KeyError, TypeError):
                pass
            raise ApiError(message, uncertain=mutation and response.status_code >= 500)
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise ApiError('Сервер повернув відповідь не у форматі JSON.', uncertain=mutation) from error

    def list_databases(self):
        return self.request('GET', '/databases')

    def create_database(self, name):
        return self.request('POST', '/databases', {'name': name})

    def get_database(self, db_id):
        return self.request('GET', f'/databases/{db_id}')

    def create_table(self, db_id, name, columns):
        return self.request('POST', f'/databases/{db_id}/tables', {'name': name, 'columns': columns})

    def get_table(self, db_id, table_id):
        return self.request('GET', f'/databases/{db_id}/tables/{table_id}')

    def delete_table(self, db_id, table_id):
        return self.request('DELETE', f'/databases/{db_id}/tables/{table_id}')

    def add_row(self, db_id, table_id, values):
        return self.request('POST', f'/databases/{db_id}/tables/{table_id}/rows', {'values': values})

    def update_row(self, db_id, table_id, row_id, updates):
        return self.request('PATCH', f'/databases/{db_id}/tables/{table_id}/rows/{row_id}', {'updates': updates})

    def remove_duplicates(self, db_id, table_id):
        return self.request('POST', f'/databases/{db_id}/tables/{table_id}/remove-duplicates')

    def import_database(self, document):
        return self.request('POST', '/databases/import', document)

    def export_database(self, db_id):
        return self.request('GET', f'/databases/{db_id}/export')
