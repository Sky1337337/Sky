from pathlib import Path
import json
from unittest.mock import patch

import pytest
from PIL import Image

from education import EducationBank, normalize, question_text, recognize_image


@pytest.fixture(scope='module')
def bank():
    return EducationBank()


def test_all_blocks_and_images_packaged(bank):
    assert len(bank.blocks) == 7
    assert len(bank.questions) == 2302
    assert len({q.id for q in bank.questions}) == 2302
    images = [q for q in bank.questions if q.image]
    assert len(images) == 210
    assert all(bank.image_path(q) for q in images)
    assert all(q.question and q.answer for q in bank.questions)
    question = next(q for q in bank.questions if q.id == 'weapons:306')
    assert question.answer == 'рамка зі стволом та спусковою скобою'


def test_retrieval_tolerates_punctuation_ocr_and_block_selection(bank):
    results = bank.search('Яка відстань найбільш ефективного вогню з пістолета Форт 12?', block='weapons')
    assert results[0].question.id == 'weapons:3'
    assert results[0].question.answer == 'до 50 м'
    text = next(q.question for q in bank.questions if q.id == 'medical:1')
    assert bank.search(text.replace('а', 'о', 1), block='medical')[0].question.block == 'medical'
    assert bank.search('Це незнайоме запитання про ремонт велосипеда') == []
    assert bank.search('   ') == []


def test_identical_wording_keeps_distinct_source_answers(bank):
    query = next(q.question for q in bank.questions if q.id == 'safety:5')
    results = bank.search(query, block='safety')
    answers = {m.question.answer for m in results if m.score == 1}
    assert 'Повернути затвор у переднє положення' in answers
    assert any('спуск курка' in answer for answer in answers)


def test_ocr_phone_chrome_and_options_removed():
    query = '17:25\nГоловна Навчання\nIV. 456. Яка з тактико-технічних\nхарактеристик зброї притаманна АКС-74У?\nВаріант 1'
    assert normalize(question_text(query)) == normalize('Яка з тактико-технічних характеристик зброї притаманна АКС-74У?')


@pytest.mark.parametrize('number', [260, 306, 456])
def test_visual_match_disambiguates_same_question_text(bank, number):
    q = next(q for q in bank.questions if q.id == f'weapons:{number}')
    # A scaled bank illustration placed inside a larger screenshot, not an exact-file hash.
    with Image.open(bank.image_path(q)) as source:
        photo = source.convert('RGB')
    photo = photo.resize((round(photo.width*.85), round(photo.height*.85)))
    screenshot = Image.new('RGB', (photo.width+90, photo.height+170), 'white')
    screenshot.paste(photo, (35, 85))
    results = bank.search(q.question, block='weapons', image=screenshot)
    assert results[0].question.id == q.id
    assert results[0].visual > .65


def test_missing_ukrainian_ocr_reports_action():
    import pytesseract
    with patch('education.shutil.which', return_value='/usr/bin/tesseract'), patch.object(pytesseract, 'get_languages', return_value=['eng']):
        with pytest.raises(RuntimeError, match='ukr'):
            recognize_image(Image.new('RGB', (200, 200), 'white'))


def test_bundled_data_lookup_does_not_depend_on_current_directory(bank, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert len(EducationBank().questions) == 2302
