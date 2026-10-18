import time
from unittest.mock import patch

import pytest
from PIL import Image

from ui import DetectivePortalPro
from app_state import runtime


@pytest.fixture
def app():
    with patch('ui.WarCrimeController.register_hotkey'), patch('ui.settings.save'):
        app = DetectivePortalPro()
        app.show_education()
        yield app
        runtime.reset()
        app.on_close()


def test_browse_copy_and_navigation(app):
    page = app.education_page
    page.block.set(page.bank.blocks['weapons'])
    page.browse()
    assert len(page.matches) == 458
    assert page.shown == 15
    page.copy_answer('Тестова відповідь')
    assert app.clipboard_get() == 'Тестова відповідь'
    page._show_more()
    assert page.shown == 30
    app.show_dashboard()
    app.show_education()
    app.update()
    assert app.page_title.cget('text') == 'Освітній портал'


def test_clipboard_image_and_async_result(app):
    page = app.education_page
    with patch('education_ui.ImageGrab.grabclipboard', return_value=Image.new('RGB', (300, 220), 'white')), patch('education_ui.recognize_image', return_value='Яка відстань найбільш ефективного вогню з пістолета Форт 12?'), patch.object(page.bank, 'search', return_value=page.bank.search('Яка відстань найбільш ефективного вогню з пістолета Форт 12?')):
        assert page._paste_shortcut() == 'break'
        deadline = time.monotonic()+5
        while page.busy and time.monotonic() < deadline:
            app.update()
            time.sleep(.02)
    assert not page.busy
    assert page.matches[0].question.id == 'weapons:3'
    assert 'Форт 12' in page.text.get('1.0', 'end')
    page.clear()
    assert page.source_image is None
    assert page.matches == []


def test_text_paste_stays_available(app):
    with patch('education_ui.ImageGrab.grabclipboard', return_value=None):
        assert app.education_page._paste_shortcut() is None


def test_ctrl_v_on_focused_textbox_pastes_image(app):
    page = app.education_page
    app.update()
    page.text.focus_set()
    app.update()
    with patch('education_ui.ImageGrab.grabclipboard', return_value=Image.new('RGB', (120, 120), 'white')), patch.object(page, 'set_image') as paste:
        page.text._textbox.event_generate('<Control-v>')
        app.update()
        paste.assert_called_once()
