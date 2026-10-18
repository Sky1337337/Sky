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
    assert question.answer == '(рамка зі стволом та спусковою скобою)'


def test_retrieval_tolerates_punctuation_ocr_and_block_selection(bank):
    results = bank.search('Яка відстань найбільш ефективного вогню з пістолета Форт 12?', block='weapons')
    assert results[0].question.id == 'weapons:3'
    assert results[0].question.answer == '(до 50 м)'
    text = next(q.question for q in bank.questions if q.id == 'medical:1')
    assert bank.search(text.replace('а', 'о', 1), block='medical')[0].question.block == 'medical'
    assert bank.search('Це незнайоме запитання про ремонт велосипеда') == []
    assert bank.search('   ') == []


def test_duplicate_parenthetical_answers_are_one_per_line_and_without_labels(bank):
    # Use the exact wording stored in the bank; all variants for this repeated
    # question should be returned as parenthetical explanations only.
    query = "У яких випадках поліцейський уповноважений застосовувати вогнепальну зброю?\n1.\nперший варіант\n2.\nдругий варіант"
    answers = bank.duplicate_parenthetical_answers(query)
    assert len(answers) > 2
    assert all('зазначене у п.п.' not in answer for answer in answers)
    assert all('(' not in answer and ')' not in answer for answer in answers)
    assert all(answer.strip() for answer in answers)


def test_duplicate_summary_works_when_only_question_is_pasted(bank):
    query = 'У яких випадках поліцейський уповноважений застосовувати вогнепальну зброю?'
    answers = bank.duplicate_parenthetical_answers(query)
    assert len(answers) > 2
    assert all('зазначене у п.п.' not in answer for answer in answers)
    assert all('(' not in answer and ')' not in answer for answer in answers)


def test_unique_question_does_not_use_duplicate_summary(bank):
    query = 'Яка відстань найбільш ефективного вогню з пістолета Форт 12?\n1.\nдо 50 м\n2.\nдо 100 м'
    assert bank.duplicate_parenthetical_answers(query) == []


def test_identical_wording_keeps_distinct_source_answers(bank):
    query = next(q.question for q in bank.questions if q.id == 'safety:5')
    results = bank.search(query, block='safety')
    answers = {m.question.answer for m in results if m.score == 1}
    assert '(Повернути затвор у переднє положення)' in answers
    assert any('спуск курка' in answer for answer in answers)


def test_ocr_phone_chrome_and_options_removed():
    query = '17:25\nГоловна Навчання\nIV. 456. Яка з тактико-технічних\nхарактеристик зброї притаманна АКС-74У?\nВаріант 1'
    assert normalize(question_text(query)) == normalize('Яка з тактико-технічних характеристик зброї притаманна АКС-74У?')


@pytest.mark.parametrize('question_id, expected', [
    ('life:1', 'відділу'),
    ('medical:46', 'комплекс реанімаційних дій, які сприяють насиченню киснем життєво важливих органів'),
    ('force:22', 'характеру правопорушення; індивідуальних особливостей особи, яка вчинила правопорушення'),
    ('weapons:36', 'вірна відповідь не вказана'),
    ('safety:5', 'Повернути затвор у переднє положення'),
    ('tactics:59', 'вірної відповіді не має'),
    ('psychology:18', 'Роздратованість, невдоволення, неспокій'),
])
def test_parenthetical_summary_is_available_in_every_real_block(bank, question_id, expected):
    question = next(q for q in bank.questions if q.id == question_id)
    answers = bank.duplicate_parenthetical_answers(question.question, block=question.block)
    assert expected in answers
    assert answers == bank.duplicate_parenthetical_answers(question.question)


def make_bank(tmp_path, rows):
    blocks = list(dict.fromkeys(row['block'] for row in rows))
    data = {
        'blocks': [{'id': block, 'title': block} for block in blocks],
        'questions': [
            {'id': f"{row['block']}:{index}", 'number': index, **row}
            for index, row in enumerate(rows, 1)
        ],
    }
    (tmp_path / 'questions.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return EducationBank(tmp_path)


@pytest.mark.parametrize('block', ['life', 'medical', 'force', 'weapons', 'safety', 'tactics', 'psychology'])
def test_parenthetical_summary_uses_the_same_rules_in_all_blocks(tmp_path, block):
    bank = make_bank(tmp_path, [
        {'block': block, 'question': 'Що потрібно зробити?', 'answer': answer}
        for answer in [
            'варіант 1 (перша відповідь)',
            'варіант 2 (друга відповідь)',
            'варіант 3 (ПЕРША ВІДПОВІДЬ!)',
        ]
    ])
    assert bank.duplicate_parenthetical_answers('Що потрібно зробити?', block=block) == ['перша відповідь', 'друга відповідь']


def test_parenthetical_summary_preserves_nested_and_collects_only_parenthetical_text(tmp_path):
    bank = make_bank(tmp_path, [
        {'block': 'medical', 'question': 'Які дії потрібні?', 'answer': answer}
        for answer in [
            'Усі відповіді вірні (перша дія (уточнення); друга дія).',
            'опис (третя дія) сторонній текст (четверта дія) кінець',
            'відповідь без дужок',
        ]
    ])
    assert bank.duplicate_parenthetical_answers('Які дії потрібні?') == [
        'перша дія (уточнення); друга дія',
        'третя дія; четверта дія',
    ]


def test_parenthetical_summary_keeps_a_single_distinct_answer_for_duplicate_rows(tmp_path):
    bank = make_bank(tmp_path, [
        {'block': 'safety', 'question': 'Що робити?', 'answer': answer}
        for answer in ['Варіант 1 (Перша відповідь)', 'Варіант 2 (перша відповідь!)']
    ])
    assert bank.duplicate_parenthetical_answers('Що робити?') == ['Перша відповідь']


def test_parenthetical_summary_obeys_block_selection(tmp_path):
    bank = make_bank(tmp_path, [
        {'block': block, 'question': 'Що робити?', 'answer': f'({answer})'}
        for block, answer in [('medical', 'допомога'), ('medical', 'захист'), ('safety', 'перевірка'), ('safety', 'огляд')]
    ])
    assert bank.duplicate_parenthetical_answers('Що робити?', block='medical') == ['допомога', 'захист']
    assert bank.duplicate_parenthetical_answers('Що робити?', block='safety') == ['перевірка', 'огляд']
    assert bank.duplicate_parenthetical_answers('Що робити?') == ['допомога', 'захист', 'перевірка', 'огляд']
    assert bank.duplicate_parenthetical_answers('Що робити?', block='missing') == []


def test_parenthetical_summary_does_not_use_the_search_result_limit(tmp_path):
    bank = make_bank(tmp_path, [
        {'block': 'force', 'question': 'Які заходи потрібні?', 'answer': f'(відповідь {index})'}
        for index in range(45)
    ])
    assert bank.duplicate_parenthetical_answers('Які заходи потрібні?') == [f'відповідь {index}' for index in range(45)]


def test_parenthetical_summary_does_not_merge_different_scenarios(tmp_path):
    bank = make_bank(tmp_path, [
        {'block': 'tactics', 'question': question, 'answer': '(відповідь)'}
        for question in [
            'Ви перебуваєте в кімнаті. Які ваші дії?',
            'Ви перебуваєте надворі. Які ваші дії?',
        ]
    ])
    assert bank.duplicate_parenthetical_answers('Ви перебуваєте в кімнаті. Які ваші дії?') == []
    assert bank.duplicate_parenthetical_answers('Які ваші дії?') == []


@pytest.mark.parametrize('options', [
    '\n1.\nПерший варіант\n2.\nДругий варіант',
    '\nА) Перший варіант\nБ) Другий варіант',
    '\nA. Перший варіант\nB. Другий варіант',
])
def test_question_text_separates_options_from_prompts_without_a_question_mark(options):
    question = 'Серцево-легенева реанімація це:'
    assert question_text(f'Питання № 46\n{question}{options}') == question


def test_question_text_keeps_internal_question_marks_and_relative_words(bank):
    question = next(q.question for q in bank.questions if q.id == 'medical:189')
    assert question_text(question + '\n1) Перший варіант\n2) Другий варіант') == question
    scenario = 'У приміщенні, що руйнується, ви почули сигнал. Які ваші дії?'
    assert question_text(scenario) == scenario


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
