from unittest.mock import patch
import pytest
from openpyxl import Workbook
from ui import DetectivePortalPro, runtime, browser, repo, settings

@pytest.fixture
def app():
    with patch('ui.WarCrimeController.register_hotkey'):
        app = DetectivePortalPro()
    yield app
    runtime.reset()
    app.on_close()

def test_events_after_navigation(app):
    for page in (app.show_settings, app.show_war_crime, app.show_dashboard):
        page()
        app.event_queue.put(('filled', 1, 2, 'Тест', 3))
        app.event_queue.put(('chrome', False))
        app._drain_events()
        app.update()
    assert app.last_person == 'Тест'

def test_log_survives_navigation(app):
    app.log('Перевірка журналу')
    app.show_settings()
    app.log('Подія у налаштуваннях')
    app.show_dashboard()
    assert 'Перевірка журналу' in app.log_box.get('1.0', 'end')
    assert 'Подія у налаштуваннях' in app.log_box.get('1.0', 'end')
    assert app.log_box.cget('state') == 'disabled'

def test_new_excel_resets_position(app, tmp_path):
    path = tmp_path / 'people.xlsx'
    wb = Workbook(); wb.active.append(['Прізвище', 'Ім’я']); wb.active.append(['Тест', 'Особа']); wb.save(path)
    browser.current = 8
    with patch('ui.filedialog.askopenfilename', return_value=str(path)):
        app.choose_people_excel()
    assert browser.current == 0
    assert len(repo.records) == 1

@pytest.mark.parametrize('delay,port', [('nan', '9222'), ('0.2', '70000')])
def test_settings_rejected_atomically(app, delay, port):
    app.show_settings()
    before = (settings.action_delay, settings.chrome_debug_port)
    for entry, value in zip(app.settings_entries, [delay, port, 'results']):
        entry.delete(0, 'end'); entry.insert(0, value)
    with patch('ui.messagebox.showerror') as error:
        app.save_settings()
    error.assert_called_once()
    assert (settings.action_delay, settings.chrome_debug_port) == before

def test_pause_toggle(app):
    runtime.running = True
    app.toggle_pause(); assert runtime.pause_event.is_set()
    app.toggle_pause(); assert not runtime.pause_event.is_set()

def test_connect_progress_and_retry_after_error(app):
    attempts = []

    def connect(log):
        log('Очікую готовності Chrome…', 'info')
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError('Час очікування вичерпано; повтори підключення')
        log('Chrome підключено', 'success')

    with patch('ui.browser.connect', side_effect=connect):
        app.connect_chrome()
        app.worker.join(timeout=2)
        assert not app.worker.is_alive()
        app._drain_events()
        assert app.side_chrome.cget('text') == '● Помилка Chrome'
        assert app.stat_status.cget('text') == 'Помилка'
        assert 'Час очікування вичерпано' in app.log_box.get('1.0', 'end')

        app.connect_chrome()
        app.worker.join(timeout=2)
        assert not app.worker.is_alive()
        app._drain_events()
        assert app.side_chrome.cget('text') == '● Chrome підключено'
        assert app.stat_status.cget('text') == 'Готово'
        assert 'Очікую готовності Chrome' in app.log_box.get('1.0', 'end')
    assert len(attempts) == 2
