"""Offline question bank, tolerant text retrieval and screenshot comparison."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import math
import os
from pathlib import Path
import re
import shutil
import unicodedata

DATA_DIR = Path(__file__).resolve().parent / 'education_data'


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', text).lower().replace('’', "'").replace('ʼ', "'")
    text = re.sub(r'^\s*(?:[ivxlcі]+\.\s*)?\d+\.\s*', '', text)
    return ' '.join(re.findall(r'[\w]+', text, re.UNICODE))


def question_text(text: str) -> str:
    """Remove phone chrome and answer options; keep the first visible question."""
    text = text.strip()
    numbered = re.search(r'(?:^|\n)\s*(?:[IVXLCІМ]+\.\s*)?\d{1,3}\.\s*(?=[А-ЯІЇЄҐ])', text, re.I)
    if numbered:
        text = text[numbered.end():]
    else:
        start = re.search(r'\b(?:Яка|Яке|Які|Яку|Який|Як|Що|Чи|Коли|Кому|Куди|Де|Скільки|З якою|З яких|Для чого|До якого|На якій|У яких|В яких)\b', text)
        if start:
            text = text[start.start():]
    if '?' in text:
        text = text.split('?', 1)[0] + '?'
    else:
        text = re.split(r'\n\s*(?:Відповідь|Варіант)\b', text, maxsplit=1)[0]
    return text


@dataclass(frozen=True)
class Question:
    id: str
    block: str
    number: int
    question: str
    answer: str
    image: str | None = None


@dataclass(frozen=True)
class Match:
    question: Question
    score: float
    visual: float = 0.0


class EducationBank:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        data = json.loads((self.data_dir / 'questions.json').read_text(encoding='utf-8'))
        self.blocks = {b['id']: b['title'] for b in data['blocks']}
        self.questions = [Question(**q) for q in data['questions']]
        self._normalized = {q.id: normalize(question_text(q.question)) for q in self.questions}
        self._tokens = {q.id: set(self._normalized[q.id].split()) for q in self.questions}
        freq = Counter(t for words in self._tokens.values() for t in words)
        self._idf = {t: math.log(1 + len(self.questions) / count) for t, count in freq.items()}
        self._visual = None

    def image_path(self, question: Question) -> Path | None:
        if not question.image:
            return None
        path = (self.data_dir / question.image).resolve()
        if not path.is_relative_to(self.data_dir.resolve()) or not path.is_file():
            return None
        return path

    def text_scores(self, query: str, block: str | None = None) -> list[Match]:
        raw = question_text(query)
        normalized = normalize(raw)
        if not normalized:
            return []
        words = set(normalized.split())
        total = sum(self._idf.get(t, 1) for t in words)
        results = []
        for q in self.questions:
            if block and q.block != block:
                continue
            ref = self._normalized[q.id]
            tokens = self._tokens[q.id]
            common = sum(self._idf.get(t, 1) for t in words & tokens)
            coverage = common / max(total, 1)
            precision = common / max(sum(self._idf.get(t, 1) for t in tokens), 1)
            overlap = 2 * coverage * precision / max(coverage + precision, .001)
            # Sequence matching tolerates OCR misspellings without equating all common words.
            ratio = SequenceMatcher(None, normalized, ref, autojunk=False).ratio()
            score = 1.0 if normalized == ref else .55 * overlap + .45 * ratio
            results.append(Match(q, score))
        return sorted(results, key=lambda m: (-m.score, m.question.block, m.question.number))

    def search(self, query: str, block: str | None = None, image=None, limit: int = 12) -> list[Match]:
        number = re.fullmatch(r'\s*№?\s*(\d+)\s*', query)
        if number and image is None:
            return [Match(q, 1) for q in self.questions if q.number == int(number[1]) and (not block or q.block == block)][:limit]
        text = self.text_scores(query, block)
        if image is None:
            return [m for m in text if m.score >= .34][:limit]
        candidates = [q for q in self.questions if q.image and (not block or q.block == block)]
        if text and text[0].score >= .55:
            allowed = {m.question.id for m in text if m.score >= text[0].score-.18}
            candidates = [q for q in candidates if q.id in allowed]
        if self._visual is None:
            self._visual = VisualIndex(self)
        visual = self._visual.scores(image, candidates)
        by_id = {m.question.id: m for m in text}
        results = []
        has_text = bool(text and text[0].score >= .40)
        for q in self.questions:
            if block and q.block != block:
                continue
            ts = by_id[q.id].score if q.id in by_id else 0
            vs = visual.get(q.id, 0)
            # A diagram alone cannot identify which of its numbered parts was asked about.
            score = .58 * ts + .42 * vs if has_text else vs
            if (vs >= .50 and (ts >= .30 or not has_text)) or ts >= .80:
                results.append(Match(q, score, vs))
        return sorted(results, key=lambda m: (-m.score, -m.visual, m.question.number))[:limit]


class VisualIndex:
    """Match a bank crop inside a screenshot, preserving repeated-diagram candidates."""
    def __init__(self, bank: EducationBank):
        import cv2
        self.cv2 = cv2
        self.bank = bank
        self.sift = cv2.SIFT_create(nfeatures=700)
        self.cache = {}

    def _gray(self, image):
        import numpy as np
        cv = self.cv2
        array = cv.cvtColor(np.asarray(image.convert('RGB')), cv.COLOR_RGB2GRAY)
        if max(array.shape) > 1500:
            array = cv.resize(array, None, fx=1500/max(array.shape), fy=1500/max(array.shape))
        return array

    def scores(self, image, candidates: list[Question]) -> dict[str, float]:
        import numpy as np
        from PIL import Image
        cv = self.cv2
        query = self._gray(image)
        keypoints, descriptors = self.sift.detectAndCompute(query, None)
        if descriptors is None:
            return {}
        query_edges = cv.Canny(query, 70, 160)
        matcher = cv.BFMatcher(cv.NORM_L2)
        scores = {}
        for q in candidates:
            if q.id not in self.cache:
                path = self.bank.image_path(q)
                if not path:
                    continue
                with Image.open(path) as source:
                    ref = self._gray(source)
                kp, des = self.sift.detectAndCompute(ref, None)
                self.cache[q.id] = ref, kp, des
            ref, kp, des = self.cache[q.id]
            # Thin springs and small plain parts may not contain enough SIFT keypoints.
            if des is None or len(kp) < 100:
                fallback = self._template_score(ref, query_edges)
                if fallback >= .72:
                    scores[q.id] = .95 * fallback
            if des is None or len(des) < 4:
                continue
            pairs = matcher.knnMatch(des, descriptors, k=2)
            good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .72 * pair[1].distance]
            if len(good) < 6:
                continue
            src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            matrix, inliers = cv.findHomography(src, dst, cv.RANSAC, 4.0)
            if matrix is None or inliers is None or int(inliers.sum()) < 6:
                continue
            try:
                inverse = np.linalg.inv(matrix)
            except np.linalg.LinAlgError:
                continue
            aligned = cv.warpPerspective(query, inverse, (ref.shape[1], ref.shape[0]), borderValue=255)
            a = cv.GaussianBlur(ref, (3, 3), 0).astype('float32')
            b = cv.GaussianBlur(aligned, (3, 3), 0).astype('float32')
            foreground = (a < 220) | (b < 220)
            error = float(np.abs(a-b)[foreground].mean()) if foreground.any() else 255
            appearance = max(0.0, 1 - error / 100)
            support = min(1.0, int(inliers.sum()) / 18)
            scores[q.id] = max(scores.get(q.id, 0), appearance * support)
        return scores

    def _template_score(self, ref, query_edges):
        cv = self.cv2
        edges = cv.Canny(ref, 70, 160)
        if cv.countNonZero(edges) < 12:
            return 0.0
        best = 0.0
        for scale in (.4, .55, .7, .85, 1., 1.15, 1.3, 1.5, 1.8, 2.):
            width, height = round(ref.shape[1]*scale), round(ref.shape[0]*scale)
            if min(width, height) < 8 or width > query_edges.shape[1] or height > query_edges.shape[0]:
                continue
            template = cv.resize(edges, (width, height), interpolation=cv.INTER_AREA)
            _, score, _, _ = cv.minMaxLoc(cv.matchTemplate(query_edges, template, cv.TM_CCOEFF_NORMED))
            best = max(best, score)
        return best


def recognize_image(image) -> str:
    """Use installed Ukrainian Tesseract; never silently OCR Cyrillic with English only."""
    import pytesseract
    from PIL import ImageOps
    config_path = Path(__file__).resolve().parent / 'war_crime_config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    executable = os.environ.get('TESSERACT_CMD') or config.get('tesseract_path') or shutil.which('tesseract')
    if not executable:
        executable = next((p for p in (r'C:\Program Files\Tesseract-OCR\tesseract.exe', r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe') if Path(p).is_file()), None)
    if not executable:
        raise RuntimeError('Для розпізнавання скриншотів установіть Tesseract OCR та українську мову (ukr). Пошук за текстом доступний без нього.')
    pytesseract.pytesseract.tesseract_cmd = executable
    languages = pytesseract.get_languages(config='')
    if 'ukr' not in languages:
        raise RuntimeError('У Tesseract відсутня українська мова ukr. Додайте ukr.traineddata до папки tessdata. Можна вставити текст запитання вручну.')
    lang = '+'.join(x for x in ('ukr', 'eng') if x in languages)
    source = ImageOps.exif_transpose(image).convert('RGB')
    if source.width < 900:
        source = source.resize((source.width*2, source.height*2))
    return pytesseract.image_to_string(source, lang=lang, config='--psm 6', timeout=40).strip()
