import time
from unittest.mock import patch

import pytest
import customtkinter as ctk
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


def wait_for_search(app):
    deadline = time.monotonic() + 5
    while app.education_page.busy and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert not app.education_page.busy


@pytest.mark.parametrize('question_id, expected', [
    ('life:70', ['для висоти будівлі до 9 поверхів',
                 'на відстані не ближче половини висоти будівлі плюс 3-5 метрів']),
    ('medical:379', ['таблетку глюкози або декстрози', 'цукерку або кубик цукру']),
    ('force:68', ['Яких незаконно позбавлено волі']),
    ('weapons:376', ['важіль', 'перевідник']),
    ('safety:10', ['Протягом тижня']),
    ('tactics:59', ['встановлення контакту; вільна розповідь; відтворення ситуації',
                    'вірної відповіді не має']),
    ('psychology:29', ['Відсутність напруженості і конфліктності в колективі',
                       'Низька плинність кадрів']),
])
def test_all_blocks_show_and_copy_parenthetical_variants(app, question_id, expected):
    page = app.education_page
    question = next(q for q in page.bank.questions if q.id == question_id)
    page.block.set(page.bank.blocks[question.block])
    page.text.insert('1.0', question.question + '\n1.\nперший варіант\n2.\nдругий варіант')
    page.search()
    wait_for_search(app)
    assert page.summary_answers == expected
    assert page.matches == []
    card, = page.results.winfo_children()
    labels = [child.cget('text') for child in card.winfo_children()
              if isinstance(child, ctk.CTkLabel)]
    assert labels == ['\n'.join(expected)]
    button, = [child for child in card.winfo_children() if isinstance(child, ctk.CTkButton)]
    button.invoke()
    assert app.clipboard_get() == '\n'.join(expected)
    page.browse()
    assert page.summary_answers is None
    assert page.matches
    page.clear()
    assert page.summary_answers is None
    assert page.matches == []


def test_screenshot_repeated_question_uses_same_parentheses_only_list(app):
    page = app.education_page
    question = next(q for q in page.bank.questions if q.id == 'psychology:29')
    with patch('education_ui.recognize_image', return_value=question.question), \
            patch.object(page.bank, 'search') as visual_search:
        page.set_image(Image.new('RGB', (300, 220), 'white'))
        wait_for_search(app)
    visual_search.assert_not_called()
    assert page.summary_answers == [
        'Відсутність напруженості і конфліктності в колективі', 'Низька плинність кадрів']
