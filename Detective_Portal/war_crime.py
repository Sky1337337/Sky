"""F6 assistant for reviewing public source text and searching an already open registry.

Fills a draft search and draft fields, but NEVER submits or saves a new person record.
"""
from __future__ import annotations

import json
import os
import shutil
import re
import threading
import time
from pathlib import Path
from tkinter import messagebox, filedialog

from app_state import APP_DIR

CONFIG_FILE = APP_DIR / 'war_crime_config.json'
FIELD_KEYS = ['surname', 'name', 'patronymic', 'birth', 'search']
FIELD_LABELS = {'surname': 'Прізвище (пошук)', 'name': "Ім’я (пошук)", 'patronymic': 'По батькові (пошук)', 'birth': 'Дата народження (пошук)', 'search': 'Кнопка «Знайти»'}

NAME_MAP = {'дмитрий': 'Дмитро', 'александр': 'Олександр', 'алексей': 'Олексій', 'андрей': 'Андрій', 'иван': 'Іван', 'николай': 'Микола', 'михаил': 'Михайло', 'сергей': 'Сергій', 'владимир': 'Володимир', 'евгений': 'Євген', 'юрий': 'Юрій', 'павел': 'Павло', 'петр': 'Петро', 'федор': 'Федір', 'артем': 'Артем', 'денис': 'Денис', 'виктор': 'Віктор', 'василий': 'Василь', 'анатолий': 'Анатолій', 'игорь': 'Ігор', 'илья': 'Ілля', 'максим': 'Максим', 'роман': 'Роман', 'анна': 'Анна', 'елена': 'Олена', 'ольга': 'Ольга', 'наталья': 'Наталія', 'татьяна': 'Тетяна'}
PATRONYMIC_MAP = {'иванович': 'Іванович', 'александрович': 'Олександрович', 'алексеевич': 'Олексійович', 'сергеевич': 'Сергійович', 'андреевич': 'Андрійович', 'михайлович': 'Михайлович', 'николаевич': 'Миколайович', 'владимирович': 'Володимирович', 'евгеньевич': 'Євгенович', 'петрович': 'Петрович', 'васильевич': 'Васильович', 'игоревич': 'Ігорович'}
DATE_RE = re.compile(r'(?<!\d)([0-3]?\d)[.\-/]([01]?\d)[.\-/]((?:19|20)\d{2})(?!\d)')
# Allow OCR to insert spaces around date separators.
DATE_FLEX_RE = re.compile(r'(?<!\d)([0-3]?\d)\s*[.\-/]\s*([01]?\d)\s*[.\-/]\s*((?:19|20)\d{2})(?!\d)')

def find_birth_date(text: str):
    """Return a valid calendar date or None; do not fabricate missing digits."""
    from datetime import date as real_date
    for regex in (DATE_RE, DATE_FLEX_RE):
        for match in regex.finditer(text):
            try:
                day, month, year = map(int, match.groups())
                real_date(year, month, day)
                return match
            except ValueError:
                continue
    return None

FULLNAME_RE = re.compile(r'(?<![А-Яа-яЁёІіЇїЄєҐґ])([А-ЯЁІЇЄҐ][а-яёіїєґ-]+)\s+([А-ЯЁІЇЄҐ][а-яёіїєґ-]+)\s+([А-ЯЁІЇЄҐ][а-яёіїєґ-]+)')


def ua_word(word: str, kind: str = '') -> str:
    w = word.lower()
    known = NAME_MAP if kind == 'name' else PATRONYMIC_MAP if kind == 'patronymic' else {}
    if w in known:
        return known[w]
    # Approximation only: surnames and regional names may require manual verification.
    w = w.replace('ий', 'ий').replace('ы', 'и').replace('э', 'е').replace('ё', 'ьо').replace('ъ', '').replace('и', 'і').replace('щ', 'щ')
    w = w.replace('свє', 'свє')
    if kind == 'surname' and w.startswith('све'):
        w = 'свє' + w[3:]
    return w.capitalize()


def parse_text(text: str) -> dict:
    normalized = re.sub(r'\s+', ' ', text)
    date = find_birth_date(normalized)
    candidates = list(FULLNAME_RE.finditer(normalized))
    # Prioritize names close to a birth date, typically in the same Telegram post.
    match = min(candidates, key=lambda m: abs(m.start() - date.start())) if candidates and date else (candidates[0] if candidates else None)
    if not match:
        raise ValueError('Не вдалося знайти ПІБ (три слова з великої літери). Перевір OCR або встав текст вручну.')
    if not date:
        raise ValueError('Не вдалося знайти дату народження у форматі ДД.ММ.РРРР.')
    d, m, y = map(int, date.groups())
    import datetime
    datetime.date(y, m, d)
    parts = match.groups()
    return {'surname': ua_word(parts[0], 'surname'), 'name': ua_word(parts[1], 'name'), 'patronymic': ua_word(parts[2], 'patronymic'), 'birth': f'{d:02d}.{m:02d}.{y}', 'source_name': ' '.join(parts)}


# Extract location from the entire OCR result, including line breaks and labels.
# These are UNVERIFIED source claims: do not infer any missing location.
REGION_SUFFIX = r'(?:область|обл\.?|край|республика|респ\.?|автономн(?:ый|ій)\s+округ|АО)'
REGION_RE = re.compile(
    r'(?P<name>[А-ЯЁІЇЄҐа-яёіїєґ][А-ЯЁІЇЄҐа-яёіїєґ\-]{2,}'
    r'(?:[ \t]+[А-ЯЁІЇЄҐа-яёіїєґ][А-ЯЁІЇЄҐа-яёіїєґ\-]{2,}){0,2})'
    r'[ \t]+(?P<suffix>' + REGION_SUFFIX + r')\b', re.I)
REGION_RE_REVERSED = re.compile(r'(?:область|край|республика|респ\.)\s*[:\-]\s*([А-ЯЁІЇЄҐа-яёіїєґ\-]+(?:\s+[А-ЯЁІЇЄҐа-яёіїєґ\-]+){0,2})', re.I)
PLACE_RE = re.compile(
    r'(?<![\w])(?P<kind>город|гор\.|г\.|п\s*\.\s*п\.|пп\.|п\.|село|с\.|деревня|дер\.|пгт\.?|смт\.?|пос[её]лок\s+городского\s+типа|пос[её]лок|пос\.|селище|станица)'
    r'\s*[:.\-]?\s+(?P<name>[А-ЯЁІЇЄҐа-яёіїєґ][А-ЯЁІЇЄҐа-яёіїєґ\-]+(?:[ \t-]+[А-ЯЁІЇЄҐа-яёіїєґ][А-ЯЁІЇЄҐа-яёіїєґ\-]+){0,2})', re.I)
SETTLEMENT_KIND = {
    'город':'м','гор.':'м','г.':'м',
    'село':'с','с.':'с','деревня':'с','дер.':'с',
    'пгт':'т','пгт.':'т','смт':'т','смт.':'т','поселок городского типа':'т','посёлок городского типа':'т',
    'поселок':'щ','посёлок':'щ','пос.':'щ','п. п.':'щ','п.п.':'щ','п.':'щ','пп.':'щ','селище':'щ','станица':'с'
}

def ua_place(source: str) -> str:
    """Rough Ukrainian display spelling; preserve the source for verification."""
    if not source:
        return ''
    return ' '.join(ua_word(part) for part in source.split())

def locality_from_text(text: str) -> dict:
    lines = [re.sub(r'[ \t]+', ' ', line).strip(' ,;') for line in text.splitlines()]
    best_region = None
    best_place = None
    for line in lines:
        reg = REGION_RE.search(line)
        if reg and not best_region:
            best_region = reg.group(0)
        elif not best_region:
            reg = REGION_RE_REVERSED.search(line)
            if reg: best_region = reg.group(1)
            elif re.search(r'\bреспублика\s+[А-ЯЁІЇЄҐа-яёіїєґ-]+', line, re.I):
                best_region = re.search(r'\bреспублика\s+[А-ЯЁІЇЄҐа-яёіїєґ-]+', line, re.I).group(0)
        place = PLACE_RE.search(line)
        if place and not best_place:
            # Strip a region suffix accidentally swallowed as part of place name.
            name = re.split(r'[,;()]|\s+(?:область|обл\.|край|республика|респ\.)\b',place.group('name'),maxsplit=1,flags=re.I)[0].strip()
            best_place = (place.group('kind'),name)
    region = best_region or ''
    if region:
        region = re.sub(r'\bобл\.?$', 'область', region, flags=re.I)
        region = re.sub(r'ская(?=\s+область)', 'ська', region, flags=re.I)
        region = re.sub(r'цкая(?=\s+область)', 'цька', region, flags=re.I)
        region = re.sub(r'\bреспублика\b', 'республіка', region, flags=re.I)
        region = re.sub(r'\bавтономный\s+округ\b', 'автономний округ', region, flags=re.I)
        region = ua_place(region).replace('Область','область').replace('Край','край').replace('Республіка','Республіка')
    kind = SETTLEMENT_KIND.get(best_place[0].lower().strip(), '') if best_place else ''
    name = best_place[1] if best_place else ''
    return {'region': region, 'region_source': best_region or '',
            'settlement_type': kind, 'settlement_source': name,
            'settlement_name': ua_place(name)}


def _settlement_name_field(controls, type_ctrl):
    """Find first editable input immediately right of the tiny settlement-type dropdown.

    Works from live UIA rectangles; does not rely on absolute screen coordinates.
    """
    r = type_ctrl.rectangle()
    candidates=[]
    for c in controls:
        try:
            if not c.is_visible() or c.element_info.control_type!='Edit':
                continue
            q=c.rectangle()
            if q.width()<35 or q.height()<8:
                continue
            ydiff=abs((q.top+q.bottom-r.top-r.bottom)/2)
            dx=q.left-r.right
            if -6 <= dx <= 240 and ydiff <= 14:
                candidates.append((max(0,dx)+ydiff*10,c))
        except Exception:
            continue
    if not candidates:
        raise RuntimeError('Не знайдено поле назви одразу праворуч від «Нас.пункт»')
    return min(candidates,key=lambda x:x[0])[1]

def read_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {}


def save_config(data: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def copy_pil_image_to_windows_clipboard(image) -> bool:
    """Copy a PIL image as a genuine Windows CF_DIB bitmap (not a file path)."""
    import ctypes
    import sys
    from io import BytesIO
    if sys.platform != 'win32':
        return False
    buf = BytesIO()
    image.convert('RGB').save(buf, format='BMP')
    dib = buf.getvalue()[14:]  # Strip 14-byte BMP file header for CF_DIB
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = ctypes.c_void_p
    kernel.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel.GlobalFree.argtypes = [ctypes.c_void_p]
    user.OpenClipboard.argtypes = [ctypes.c_void_p]
    user.OpenClipboard.restype = ctypes.c_int
    user.EmptyClipboard.restype = ctypes.c_int
    user.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user.SetClipboardData.restype = ctypes.c_void_p
    user.CloseClipboard.restype = ctypes.c_int
    GMEM_MOVEABLE = 0x0002
    CF_DIB = 8
    for _ in range(8):
        if user.OpenClipboard(None):
            break
        time.sleep(.06)
    else:
        return False
    handle = None
    try:
        handle = kernel.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not handle:
            return False
        ptr = kernel.GlobalLock(handle)
        if not ptr:
            return False
        ctypes.memmove(ptr, dib, len(dib))
        kernel.GlobalUnlock(handle)
        if not user.EmptyClipboard():
            return False
        if not user.SetClipboardData(CF_DIB, handle):
            return False
        handle = None  # Windows clipboard now owns this allocation
        return True
    finally:
        if handle:
            kernel.GlobalFree(handle)
        user.CloseClipboard()


def save_visible_photo(shot, config: dict) -> tuple[str, bool]:
    """Detect a face on the Telegram side and save a fresh face-only PNG for each F6.

    No caption or full-screen copy is saved. A failed detection does not stop OCR.
    """
    from io import BytesIO
    from datetime import datetime
    from PIL import Image
    try:
        import cv2
        import numpy as np
    except ImportError:
        return '', False

    # Telegram/source occupies left side. Do not crop a fixed central rectangle:
    # its position changes when the window size or Telegram zoom changes.
    sw, sh = shot.size
    max_source_x = min(sw, int(sw * float(config.get('source_width', .54))))
    image = shot.crop((0, 0, max_source_x, sh)).convert('RGB')
    pixels = np.asarray(image)
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    face_model = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if face_model.empty():
        return '', False
    # Multiple passes: a small frontal head or a large Telegram portrait.
    faces = face_model.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(40, 40))
    if len(faces) == 0:
        larger = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_LINEAR)
        hits = face_model.detectMultiScale(larger, scaleFactor=1.07, minNeighbors=3, minSize=(60, 60))
        faces = [(int(x/1.5),int(y/1.5),int(w/1.5),int(h/1.5)) for x,y,w,h in hits]
    if not len(faces):
        return '', False
    # Prefer the largest clearly visible face; crop head/neck but not captions.
    x,y,fw,fh = max(faces, key=lambda f: int(f[2])*int(f[3]))
    cx,cy=x+fw/2,y+fh/2
    side=int(max(fw,fh)*1.65)
    l=max(0,int(cx-side/2)); t=max(0,int(cy-side/2))
    r=min(image.width,l+side); bottom=min(image.height,t+side)
    portrait=image.crop((l,t,r,bottom))
    directory=APP_DIR/'F6_PHOTOS'
    directory.mkdir(exist_ok=True)
    photo_path=directory/('telegram_face_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.png')
    portrait.save(photo_path,format='PNG')
    try:
        copied = copy_pil_image_to_windows_clipboard(portrait)
    except Exception:
        copied = False
    return str(photo_path),copied


def screen_ocr() -> tuple[str, str, bool]:
    try:
        import pyautogui
        import pytesseract
    except ImportError as exc:
        raise RuntimeError('Для OCR встанови залежності з requirements.txt') from exc
    config = read_config()
    exe = config.get('tesseract_path')
    if not exe:
        options = [r'C:\Program Files\Tesseract-OCR\tesseract.exe', r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe']
        exe = next((item for item in options if os.path.isfile(item)), None) or shutil.which('tesseract')
    if exe:
        pytesseract.pytesseract.tesseract_cmd = exe
    from PIL import ImageOps, ImageEnhance
    shot = pyautogui.screenshot()
    # Capture source document on left, exclude target database on right.
    w, h = shot.size
    crop = shot.crop((0, 0, int(w * float(config.get('source_width', .54))), h))
    # Limit the OCR image size: the full 1080p source is slower without improving
    # typical Telegram caption recognition. OCR is performed only once per F6.
    if crop.width > 1000:
        new_height = round(crop.height * (1000 / crop.width))
        crop = crop.resize((1000, new_height))
    crop = ImageOps.grayscale(crop)
    try:
        text = pytesseract.image_to_string(crop, lang='rus+ukr', config='--psm 6')
        # Capture the photo from the SAME screenshot used for OCR, avoiding a
        # second screenshot and preserving the original image resolution.
        try:
            photo_path, copied = save_visible_photo(shot, config)
        except Exception:
            photo_path, copied = '', False  # OCR/search continues even if detection fails
        return text, photo_path, copied
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError('Tesseract OCR не встановлено або не вказано шлях до tesseract.exe') from exc
    except pytesseract.TesseractError as exc:
        raise RuntimeError('Потрібні мовні файли Tesseract: rus.traineddata та ukr.traineddata') from exc


def retry_date_ocr() -> str:
    """Higher-resolution OCR fallback, run only if fast OCR missed the date."""
    import pyautogui
    import pytesseract
    from PIL import ImageOps, ImageEnhance
    config = read_config()
    shot = pyautogui.screenshot()
    w, h = shot.size
    crop = shot.crop((0, 0, int(w * float(config.get('source_width', .54))), h))
    # Preserve small caption digits; the normal fast pass resizes to 1000 px.
    if crop.width < 1600:
        factor = min(2, 1600 / crop.width)
        crop = crop.resize((round(crop.width * factor), round(crop.height * factor)))
    gray = ImageOps.grayscale(crop)
    enhanced = ImageEnhance.Contrast(gray).enhance(1.5)
    return pytesseract.image_to_string(enhanced, lang='rus+ukr', config='--psm 11')


def _read_edit(ctrl):
    """Read the live accessible value (not the visible label)."""
    try:
        return str(ctrl.iface_value.CurrentValue)
    except Exception:
        try:
            return str(ctrl.get_value())
        except Exception:
            return None


def _type_unicode_windows(text: str):
    """Send Unicode key press/release events with correctly sized Win32 INPUT.

    The INPUT union must include MOUSEINPUT; a keyboard-only union produces
    an invalid cbSize on 64-bit Windows, and SendInput returns 0/error 87.
    """
    import ctypes
    import sys
    from ctypes import wintypes
    if sys.platform != 'win32':
        raise RuntimeError('Unicode-введення доступне лише у Windows.')

    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                    ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                    ('dwExtraInfo', ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
                    ('wParamH', wintypes.WORD)]

    class INPUTUNION(ctypes.Union):
        _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ('u',)
        _fields_ = [('type', wintypes.DWORD), ('u', INPUTUNION)]

    send = ctypes.WinDLL('user32', use_last_error=True).SendInput
    send.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    send.restype = wintypes.UINT
    data = text.encode('utf-16-le')
    events = []
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], 'little')
        events.append(INPUT(type=1, ki=KEYBDINPUT(0, unit, 0x0004, 0, 0)))
        events.append(INPUT(type=1, ki=KEYBDINPUT(0, unit, 0x0004 | 0x0002, 0, 0)))
    for i in range(0, len(events), 64):
        batch = events[i:i + 64]
        array = (INPUT * len(batch))(*batch)
        ctypes.set_last_error(0)
        count = send(len(batch), array, ctypes.sizeof(INPUT))
        if count != len(batch):
            err = ctypes.get_last_error()
            raise RuntimeError(f'Windows SendInput передав {count}/{len(batch)} подій (код {err}). Перевір права доступу до Edge.')


def _activate_edit(ctrl, search_row=None):
    """Activate the visible Edge search edit after the portal is minimized.

    UIA HTML Edit nodes often do not own an HWND; use the Edge window
    enclosing the control, then click the *fresh* edit rectangle.
    """
    import ctypes
    import pyautogui
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    # Never use ctrl.handle as an HWND: Edge accessibility nodes can expose
    # virtual handles unrelated to an actual top-level browser window.
    root = int(ctrl.top_level_parent().handle)
    if not root or not user32.IsWindow(wintypes.HWND(root)):
        raise RuntimeError('Не вдалося знайти вікно Edge для поля пошуку.')
    user32.ShowWindow(wintypes.HWND(root), 9)
    rect = ctrl.rectangle()
    if search_row is not None:
        top, bottom = search_row
        center_y = (rect.top + rect.bottom) / 2
        if not (top <= center_y <= bottom):
            raise RuntimeError('Поле не у верхньому рядку пошуку. Введення зупинено.')
    # A real mouse click gives a user-initiated foreground transition and
    # is more reliable on legacy Edge forms than UIA .set_focus().
    if rect.width() < 20 or rect.height() < 8:
        raise RuntimeError('Поле пошуку має некоректні межі; введення зупинено.')
    pyautogui.click((rect.left + rect.right)//2, (rect.top + rect.bottom)//2)
    time.sleep(.09)
    foreground = user32.GetForegroundWindow()
    if foreground != root and user32.GetAncestor(wintypes.HWND(foreground), 2) != root:
        raise RuntimeError('Edge не отримав фокус після натискання поля пошуку. Перевір, чи вікно не перекрите.')
    # If accessibility cannot confirm focus, stop rather than type into
    # another field (especially the WC_P_TYPE dropdown).
    try:
        focused = bool(ctrl.element_info.element.CurrentHasKeyboardFocus)
    except Exception:
        focused = False
    if not focused:
        raise RuntimeError('Не підтверджено фокус верхнього поля пошуку. F6 не вводив текст.')


def _write_edit(ctrl, value: str, search_row=None):
    """Write directly to the accessible search edit, NEVER type into foreground.

    UIA ValuePattern avoids the Windows focus race that sent a surname into
    the WC_P_TYPE dropdown. If Edge does not expose writable ValuePattern,
    abort safely instead of sending keystrokes to an unrelated field.
    """
    wanted = str(value).strip().upper()
    if not wanted:
        return
    rect = ctrl.rectangle()
    if search_row is not None:
        top, bottom = search_row
        cy = (rect.top + rect.bottom) / 2
        if not top <= cy <= bottom:
            raise RuntimeError('Поле поза верхнім рядком Пошук; запис зупинено.')
    errors = []
    for method in ('value_pattern', 'set_edit_text'):
        try:
            if method == 'value_pattern':
                pattern = ctrl.iface_value
                if bool(pattern.CurrentIsReadOnly):
                    raise RuntimeError('Поле доступне лише для читання')
                pattern.SetValue(wanted)
            else:
                ctrl.set_edit_text(wanted)
            time.sleep(.025)
            seen = _read_edit(ctrl)
            if seen is not None and seen.strip().upper() == wanted:
                return
            errors.append(f'{method}: прочитано {seen!r}')
        except Exception as exc:
            errors.append(f'{method}: {exc}')
    raise RuntimeError('Не вдалося заповнити верхнє поле Пошук напряму через UI Automation. '
                       'Інші поля не чіпали. ' + '; '.join(errors))


def send_search(record: dict):
    """Find the visible search controls via Windows UI Automation (no saved pixels).

    The legacy site must expose the input controls to the UIA accessibility tree.
    """
    import pyautogui
    import pyperclip
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError('Встанови pywinauto: py -m pip install -r requirements.txt') from exc

    matches = []
    for window in Desktop(backend='uia').windows():
        title = window.window_text().lower()
        if 'воєнний злочинець' in title or 'военный преступник' in title:
            matches.append(window)
    if not matches:
        raise RuntimeError('Не знайдено вікно Edge «Воєнний злочинець». Відкрий форму пошуку.')
    window = next((w for w in matches if 'edge' in w.window_text().lower()), matches[0])
    # Read accessibility nodes without changing window focus or position.
    # ValuePattern writes to the intended input regardless of active window.
    try:
        controls = window.descendants()
    except Exception as exc:
        raise RuntimeError('Немає доступу до полів Edge через Windows UI Automation.') from exc

    search_buttons = []
    for ctrl in controls:
        try:
            title = ctrl.window_text().strip().lower()
            typ = ctrl.element_info.control_type
            if typ in ('Button', 'Text') and title in ('знайти', 'найти') and ctrl.is_visible():
                search_buttons.append(ctrl)
        except Exception:
            continue
    if not search_buttons:
        raise RuntimeError('Кнопку «Знайти» не видно в дереві доступності Edge. Потрібен HTML цієї форми для надійного Selenium-пошуку.')

    # Choose the TOP search button only. Other 'Find' buttons belong to other form sections.
    search_buttons.sort(key=lambda b: (b.rectangle().top, b.rectangle().left))
    # Select four edits intersecting the exact upper search row, never the row below.
    # Coordinates are read live from the accessible controls each invocation.
    for button in search_buttons:
        rect = button.rectangle()
        cy = (rect.top + rect.bottom) / 2
        edits = []
        for ctrl in controls:
            try:
                if ctrl.element_info.control_type != 'Edit' or not ctrl.is_visible():
                    continue
                r = ctrl.rectangle()
                ey = (r.top + r.bottom) / 2
                overlap = max(0, min(r.bottom, rect.bottom) - max(r.top, rect.top))
                if (abs(ey - cy) <= 11 and overlap >= min(r.height(), rect.height()) * 0.55
                        and r.right <= rect.left + 5 and r.width() > 25):
                    edits.append(ctrl)
            except Exception:
                continue
        edits.sort(key=lambda c: c.rectangle().left)
        if len(edits) == 4:
            # Four fields must be unique and on the precise top line. Never guess.
            # Search row must remain aligned with the Find button throughout.
            band = (rect.top - 4, rect.bottom + 4)
            for key, ctrl in zip(('surname','name','patronymic','birth'), edits):
                _write_edit(ctrl, record[key], search_row=band)
            # Re-check *all* inputs: dynamic pages can erase earlier fields.
            for key, ctrl in zip(('surname','name','patronymic','birth'), edits):
                if (_read_edit(ctrl) or '').strip() != str(record[key]).strip().upper():
                    raise RuntimeError('Вебформа змінила значення одного з полів. Пошук не запущено.')
            try:
                button.click_input()
            except Exception:
                r = button.rectangle()
                pyautogui.click((r.left+r.right)//2, (r.top+r.bottom)//2)
            time.sleep(.8)
            # Confirm only the known 'not found' javascript prompt; do not auto-create or save.
            not_found = False
            try:
                from pywinauto import Desktop
                for dlg in Desktop(backend='uia').windows():
                    if not dlg.is_visible():
                        continue
                    texts = []
                    try:
                        texts = [c.window_text().lower() for c in dlg.descendants()]
                    except Exception:
                        pass
                    if any('по запиту даних не знайдено' in t or 'по запросу данных не найдено' in t for t in texts):
                        ok_buttons = [c for c in dlg.descendants() if c.element_info.control_type == 'Button' and c.window_text().strip().lower() in ('ок','ok')]
                        if ok_buttons:
                            ok_buttons[0].click_input()
                            not_found = True
                        break
            except Exception:
                pass
            return not_found
    raise RuntimeError('Не вдалося надійно знайти рівно 4 поля ВЕРХНЬОГО рядка пошуку. F6 нічого не ввів, щоб не зачепити «Тип особи».')


def _norm_label(text: str) -> str:
    return re.sub(r'[^а-яіїєґa-z0-9]+', '', text.lower().replace('ё', 'е'))


def _control_rect_center(ctrl):
    r = ctrl.rectangle()
    return (r.left+r.right)/2, (r.top+r.bottom)/2


def _form_control_by_label(controls, aliases, expected_type=('Edit', 'ComboBox'), *, side='any'):
    """Use text labels and live rectangles, not saved coordinates.

    Match label text strictly enough not to confuse Стать with Статус особи.
    """
    targets = {_norm_label(x) for x in aliases}
    labels, fields = [], []
    for c in controls:
        try:
            if not c.is_visible():
                continue
            typ=c.element_info.control_type
            rect=c.rectangle()
            if rect.width()<12 or rect.height()<8:
                continue
            name=_norm_label(c.window_text() or '')
            if typ in expected_type and rect.width()>25:
                fields.append(c)
                if name in targets:  # accessible field with its own exact label
                    return c
            if typ in ('Text','Static','Hyperlink') and name in targets:
                labels.append(c)
        except Exception:
            continue
    candidates=[]
    for lab in labels:
        r=lab.rectangle()
        for f in fields:
            fr=f.rectangle()
            # Field must start to the right of label, not on a different row
            vertical_gap=abs((fr.top+fr.bottom)-(r.top+r.bottom))/2
            right_gap=fr.left-r.right
            if -5<=right_gap<=380 and vertical_gap<20:
                candidates.append((vertical_gap*12+max(0,right_gap),f))
    if candidates:
        return min(candidates,key=lambda x:x[0])[1]
    raise RuntimeError('Не знайдено поле '+aliases[0]+' (UIA label не прив’язаний до поля)')


def _field_display(ctrl):
    try:
        typ=ctrl.element_info.control_type
        if typ=='ComboBox':
            texts=[]
            for c in ctrl.descendants():
                t=(c.window_text() or '').strip()
                if t and t not in texts: texts.append(t)
            if texts: return ' / '.join(texts[:4])
        return (_read_edit(ctrl) or ctrl.window_text() or '').strip()
    except Exception:
        return ''


def _enter_code(ctrl, value: str):
    """Select dropdown code without Enter: Enter may submit the legacy web form."""
    import pyautogui
    wanted = str(value)
    try:
        before = _field_display(ctrl)
        # Some UIA ComboBox controls allow selecting an exposed item directly.
        try:
            if ctrl.element_info.control_type == 'ComboBox':
                items = ctrl.descendants(control_type='ListItem')
                exact = [x for x in items if (x.window_text() or '').strip() == wanted]
                if exact:
                    exact[0].select()
                    selected = _field_display(ctrl)
                    if selected and selected != before:
                        return selected
        except Exception:
            pass
        ctrl.click_input()
        pyautogui.hotkey('ctrl', 'a', interval=0.02)
        pyautogui.write(wanted, interval=0.015)
        # Tab commits a native selection without submitting the form.
        pyautogui.press('tab')
        time.sleep(0.12)
        after = _field_display(ctrl)
        if not after or (after == before and wanted not in after):
            raise RuntimeError(f'Не підтверджено вибір коду {wanted}; видиме значення: {after!r}')
        return after
    except Exception as exc:
        raise RuntimeError(f'Введення коду {wanted}: {exc}') from exc


def _enter_gender(window, controls, code: str = '1'):
    """Choose the gender dropdown, not a nearby 'SEX/Стать' accessibility label.

    Legacy web selectors sometimes expose a static name ('SEX; Стать') even when
    no item has been selected. Do not accept the static name as a field value.
    """
    import pyautogui

    labels = []
    combos = []
    for c in controls:
        try:
            if not c.is_visible():
                continue
            typ = c.element_info.control_type
            name = _norm_label(c.window_text() or '')
            if name == _norm_label('Стать') and typ in ('Text', 'Static'):
                labels.append(c)
            if typ == 'ComboBox':
                combos.append(c)
        except Exception:
            continue

    candidates = []
    for label in labels:
        lr = label.rectangle()
        for combo in combos:
            cr = combo.rectangle()
            vertical = abs((cr.top + cr.bottom) - (lr.top + lr.bottom)) / 2
            gap = cr.left - lr.right
            if -3 <= gap <= 250 and vertical < 15:
                candidates.append((vertical * 20 + max(0, gap), combo))

    if not candidates:
        # Fallback to the existing label matcher when the web control exposes
        # no separate static label. Still reject unselected placeholder text.
        ctrl = _form_control_by_label(controls, ['Стать'], expected_type=('ComboBox',))
    else:
        ctrl = min(candidates, key=lambda pair: pair[0])[1]

    before = _field_display(ctrl)
    ctrl.click_input()
    pyautogui.write(str(code), interval=0.008)
    # Tab commits the selection without submitting the entire page.
    pyautogui.press('tab')
    time.sleep(0.1)
    after = _field_display(ctrl)

    def meaningful(text):
        norm = _norm_label(text)
        return bool(norm and norm not in ('sexстать', 'стать', 'sex', 'select', 'виберіть'))

    if not meaningful(after) or _norm_label(after) == _norm_label(before):
        # Some legacy SELECTs only react to keyboard selection with a popup.
        ctrl.click_input()
        pyautogui.press('home')
        pyautogui.write(str(code), interval=0.008)
        pyautogui.press('tab')
        time.sleep(0.1)
        after = _field_display(ctrl)
    if not meaningful(after) or _norm_label(after) == _norm_label(before):
        raise RuntimeError(
            f'Не вдалося підтвердити вибір статі: було {before!r}, стало {after!r}. '
            'Потрібна діагностика конкретного списку.'
        )
    return after


def _fill_text_field(ctrl, value: str):
    import pyautogui, pyperclip
    ctrl.click_input()
    pyautogui.hotkey('ctrl','a')
    pyperclip.copy(str(value))
    pyautogui.hotkey('ctrl','v')
    time.sleep(.09)
    actual=_read_edit(ctrl)
    if actual is not None and str(value).strip() not in actual.strip():
        raise RuntimeError('Текстове поле не прийняло введений текст.')
    return actual


def fill_new_person_form(record: dict) -> dict:
    """Best effort on *draft only*. Report every unresolved control rather than aborting.
    No automatic Save; statuses are unverified until a human reviews them.
    """
    from pywinauto import Desktop
    windows = [w for w in Desktop(backend='uia').windows()
               if 'воєнний злочинець' in w.window_text().lower() or 'военный преступник' in w.window_text().lower()]
    if not windows:
        raise RuntimeError('Не знайдено вікна бази для заповнення картки.')
    window=next((w for w in windows if 'edge' in w.window_text().lower()),windows[0])
    results={}
    specs=[('Тип особи',['Тип особи'],'1'),
           ('Джерело даних',['Джерело даних'],'09'),
           ('Стать',['Стать'],'1'),
           ('Громадянство',['Громадянство'],'589'),
           ('Країна',['Країна'],'589')]
    if record.get('region'):
        specs.append(('Область',['Область'],record['region']))
    else:
        results['Область']='НЕ ВИЗНАЧЕНО З TELEGRAM — залишено порожнім'
    if record.get('settlement_type'):
        specs.append(('Нас.пункт',['Нас.пункт','Нас пункт','Населений пункт'],record['settlement_type']))
    else:
        results['Нас.пункт']='НЕ ВИЗНАЧЕНО З TELEGRAM — залишено порожнім'
    specs.append(('Статус особи',['Статус особи'],'04'))
    for title,aliases,val in specs:
        try:
            controls=window.descendants() # refresh after each Enter
            ctrl=_form_control_by_label(controls,aliases)
            actual=_enter_code(ctrl,val)
            results[title]=f'код {val}; відображається: {actual or "[значення недоступне через UIA]"}'
        except Exception as exc:
            results[title]='НЕ ЗАПОВНЕНО: '+str(exc)
    # Type selector and the adjacent place-name input are TWO different controls.
    # Enter the place name only if the source contained an explicit settlement marker.
    if record.get('settlement_type') and record.get('settlement_name'):
        try:
            controls=window.descendants()
            type_ctrl=_form_control_by_label(controls,['Нас.пункт','Нас пункт','Населений пункт'])
            place_ctrl=_settlement_name_field(controls,type_ctrl)
            entered=_fill_text_field(place_ctrl,record['settlement_name'])
            results['Назва населеного пункту']=(
                f'введено: {record["settlement_name"]}; джерело: {record["settlement_source"]}; '
                f'UIA: {entered or "[нечитабельно]"}; ПЕРЕВІРИТИ НАПИСАННЯ'
            )
        except Exception as exc:
            results['Назва населеного пункту']='НЕ ЗАПОВНЕНО: '+str(exc)
    else:
        results['Назва населеного пункту']='НЕ ВИЗНАЧЕНО З TELEGRAM — залишено порожнім'
    try:
        controls=window.descendants()
        ctrl=_form_control_by_label(controls,['Додатково'],expected_type=('Edit','Document'))
        actual=_fill_text_field(ctrl,'Учасник збройної агресії РФ проти України')
        results['Додатково']='введено (не збережено); UIA: '+(actual or '[нечитабельно]')
    except Exception as exc:
        results['Додатково']='НЕ ЗАПОВНЕНО: '+str(exc)
    return results


# One keypress = one field. No automatic saving of person records.
STEP_DEFINITIONS = [
    ('Прізвище (пошук)', [], 'text', 'surname'),
    ('Ім’я (пошук)', [], 'text', 'name'),
    ('По батькові (пошук)', [], 'text', 'patronymic'),
    ('Дата народження (пошук)', [], 'text', 'birth'),
    ('Знайти (натисни F7 після вибору кнопки)', [], 'button', '__search_button__'),
    ('Тип особи', ['Тип особи'], 'code', '1'),
    ('Джерело даних', ['Джерело даних'], 'code', '09'),
    ('Стать', ['Стать'], 'code', '1'),
    ('Громадянство', ['Громадянство'], 'code', '589'),
    ('Країна', ['Країна'], 'code', '589'),
    ('Область', ['Область'], 'code', 'region'),
    ('Тип населеного пункту', ['Нас.пункт', 'Нас пункт', 'Населений пункт'], 'code', 'settlement_type'),
    ('Назва населеного пункту', ['Нас.пункт', 'Нас пункт', 'Населений пункт'], 'place', 'settlement_name'),
    ('Статус особи', ['Статус особи'], 'code', '04'),
    ('Додатково', ['Додатково'], 'text', 'Учасник збройної агресії РФ проти України'),
    ('Наступне поле — 1', [], 'code', '1'),
    ('Наступне поле — дата', [], 'text', '01012025'),
]


def _step_target_window():
    from pywinauto import Desktop
    windows = [w for w in Desktop(backend='uia').windows()
               if 'воєнний злочинець' in w.window_text().lower()
               or 'военный преступник' in w.window_text().lower()]
    if not windows:
        raise RuntimeError('Не знайдено вікно «Воєнний злочинець». Відкрий картку в Edge.')
    return next((w for w in windows if 'edge' in w.window_text().lower()), windows[0])


def fill_single_step(index, record):
    """Enter the next value in the manually focused field and press Enter.

    Use keyboard.write for Cyrillic, because legacy web apps often ignore Ctrl+V.
    The sending operation is NOT proof that the web form accepted the value.
    """
    import pyautogui
    import keyboard
    title, _labels, _mode, spec = STEP_DEFINITIONS[index]
    value = record.get(spec, '') if spec in ('surname','name','patronymic','birth','region','settlement_type','settlement_name') else spec
    if not value:
        raise RuntimeError(f'Не визначено «{title}» у Telegram. Повтори F6 після перевірки тексту.')
    value = str(value)
    if spec == '__search_button__':
        import keyboard
        keyboard.send('enter')
        return title, 'Enter', 'Натиснуто Enter на вибраній вручну кнопці «Знайти»'
    if spec in ('surname','name','patronymic'):
        value = value.upper()
    # The user is responsible for focusing the correct field before pressing F7.
    # Avoid sending keystrokes if DetectivePortal or another app is in the foreground.
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        foreground = win32gui.GetWindowText(hwnd).lower()
        if 'edge' not in foreground and 'воєнний злочинець' not in foreground and 'военный преступник' not in foreground:
            raise RuntimeError('Активне не вікно Edge з вебформою. Клацни потрібне поле та повтори F7.')
    except ImportError:
        pass
    prior_pause = pyautogui.PAUSE
    try:
        pyautogui.PAUSE = 0.01
        # Typing instead of paste is essential for reference/autocomplete inputs.
        keyboard.write(value, delay=0.001)
        time.sleep(0.025)
        if index >= 5:
            keyboard.send('enter')
    finally:
        pyautogui.PAUSE = prior_pause
    return title, value, ('надіслано клавішами + Enter' if index >= 5 else 'надіслано клавішами без Enter') + ' (потрібна візуальна перевірка)'


class WarCrimeController:
    def __init__(self, app):
        self.app = app
        self.busy = False
        self.hotkey = None
        self.f7_hotkey = None
        self.record = None
        self.step_index = 0
        self.form_ready = False

    def register_hotkey(self):
        try:
            import keyboard
            self.hotkey = keyboard.add_hotkey('f6', lambda: self.app.after(0, self.start), suppress=False)
            self.f7_hotkey = keyboard.add_hotkey('f7', lambda: self.app.after(0, self.next_step), suppress=True)
        except Exception as exc:
            self.app.log('Глобальні F6/F7 недоступні: ' + str(exc), 'warning')

    def unregister(self):
        try:
            import keyboard
        except ImportError:
            return
        for key in (self.hotkey, self.f7_hotkey):
            if key is not None:
                try: keyboard.remove_hotkey(key)
                except Exception: pass

    def start(self):
        """F6 only opens paste-and-review window; no web form is touched."""
        if self.busy:
            return
        self.record = None
        self.step_index = 0
        self.form_ready = False
        self._paste_dialog()

    def _paste_dialog(self):
        import tkinter as tk
        import customtkinter as ctk
        from PIL import Image, ImageTk, ImageGrab

        if getattr(self, '_dialog', None) is not None:
            try:
                if self._dialog.winfo_exists():
                    self._dialog.lift()
                    return
            except Exception:
                pass
        win = ctk.CTkToplevel(self.app)
        self._dialog = win
        win.title('F6 — Встав скриншот для аналізу')
        win.geometry('740x710')
        win.minsize(620, 580)
        win.configure(fg_color=('#F2F5F7', '#151F29'))
        self._image = None
        self._preview = None
        ctk.CTkLabel(win, text='Розпізнавання картки  ·  F6', font=('Segoe UI', 19, 'bold')).pack(pady=9)
        panel = tk.Label(win, text='Очікується зображення…', bg='#1C2935', fg='white', height=15)
        panel.pack(fill='x', padx=16, pady=5)
        status = tk.StringVar(value='Зображення ще не вставлено')
        ctk.CTkLabel(win, textvariable=status, wraplength=660, text_color=('#526575', '#9DB0BF')).pack(pady=4)

        def set_image(img):
            if img is None or not hasattr(img, 'size'):
                status.set('Буфер не містить зображення. Скопіюй скриншот (Win+Shift+S).')
                return
            self._image = img.convert('RGB')
            shown = self._image.copy()
            shown.thumbnail((740, 285))
            self._preview = ImageTk.PhotoImage(shown)
            panel.configure(image=self._preview, text='', height=285)
            status.set(f'Зображення отримано: {img.width} × {img.height}')

        def paste(event=None):
            try:
                obj = ImageGrab.grabclipboard()
                # Some clipboard operations return a list of image file paths.
                if isinstance(obj, list) and obj:
                    obj = Image.open(obj[0])
                set_image(obj)
            except Exception as exc:
                status.set('Помилка вставлення: ' + str(exc))
            return 'break'

        def open_file():
            name = filedialog.askopenfilename(parent=win, filetypes=[('Зображення','*.png *.jpg *.jpeg *.bmp *.webp')])
            if name:
                try:
                    with Image.open(name) as image:
                        set_image(image)
                except Exception as exc:
                    status.set(str(exc))

        buttons=ctk.CTkFrame(win,fg_color='transparent'); buttons.pack(pady=5)
        ctk.CTkButton(buttons,text='Вставити · Ctrl+V',command=paste,fg_color='#42647B').pack(side='left',padx=4)
        ctk.CTkButton(buttons,text='Відкрити файл',command=open_file,fg_color='#42647B').pack(side='left',padx=4)
        fields=ctk.CTkFrame(win,fg_color='transparent'); fields.pack(fill='x',padx=24,pady=7)
        labels=[('surname','Прізвище'),('name','Ім’я'),('patronymic','По батькові'),('birth','Дата народження'),('region','Область / край'),('settlement_type','Тип нас. пункту'),('settlement_name','Населений пункт')]
        entries={}
        for i,(key,label) in enumerate(labels):
            ctk.CTkLabel(fields,text=label,anchor='w').grid(row=i,column=0,sticky='w',padx=5,pady=2)
            var=tk.StringVar(); entries[key]=var
            ctk.CTkEntry(fields,textvariable=var,font=('Segoe UI',12),height=30).grid(row=i,column=1,sticky='ew',padx=5,pady=2)
        fields.grid_columnconfigure(1,weight=1)

        def analyze():
            if self._image is None:
                status.set('Спочатку встав зображення.')
                return
            if self.busy:
                return
            self.busy=True
            status.set('Розпізнавання тексту…')
            source_image=self._image.copy()
            def worker():
                try:
                    import pytesseract
                    from PIL import ImageOps
                    config=read_config()
                    exe=config.get('tesseract_path') or next((x for x in [r'C:\Program Files\Tesseract-OCR\tesseract.exe',r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'] if os.path.isfile(x)),None) or shutil.which('tesseract')
                    if exe: pytesseract.pytesseract.tesseract_cmd=exe
                    from PIL import ImageEnhance, ImageFilter
                    # Telegram usually places the text below the photograph.
                    # OCR that region at increased resolution first, not the small UI preview.
                    w, h = source_image.size
                    lower = source_image.crop((0, int(h * 0.52), w, h))
                    def ocr_region(region, psm=6, threshold=False):
                        region = ImageOps.grayscale(region)
                        factor = min(3.0, max(1.7, 1500 / max(region.width, 1)))
                        region = region.resize((int(region.width * factor), int(region.height * factor)), Image.Resampling.LANCZOS)
                        region = ImageEnhance.Contrast(region).enhance(1.8)
                        region = ImageEnhance.Sharpness(region).enhance(1.6)
                        if threshold:
                            region = region.point(lambda x: 255 if x > 175 else 0)
                        return pytesseract.image_to_string(region,lang='rus+ukr',config=f'--psm {psm}')

                    txt = ocr_region(lower, 6)
                    # A partial result is useful: never wipe successful OCR because the date failed.
                    def decode(source):
                        out = locality_from_text(source)
                        try:
                            out.update(parse_text(source))
                        except (ValueError, OverflowError):
                            pass
                        return out
                    rec = decode(txt)
                    if not all(rec.get(k) for k in ('surname','name','patronymic','birth')):
                        # Retry on the same text band with binary preprocessing.
                        retry_txt = ocr_region(lower, 11, threshold=True)
                        retry_rec = decode(retry_txt)
                        if sum(bool(retry_rec.get(k)) for k in ('surname','name','patronymic','birth')) > sum(bool(rec.get(k)) for k in ('surname','name','patronymic','birth')):
                            rec = retry_rec
                        txt += '\n--- SECOND PASS ---\n' + retry_txt
                    if not all(rec.get(k) for k in ('surname','name','patronymic','birth')):
                        # Last resort: full-resolution screenshot, in case the post is laid out differently.
                        full_txt = ocr_region(source_image, 11)
                        full_rec = decode(full_txt)
                        if sum(bool(full_rec.get(k)) for k in ('surname','name','patronymic','birth')) > sum(bool(rec.get(k)) for k in ('surname','name','patronymic','birth')):
                            rec = full_rec
                        txt += '\n--- FULL IMAGE ---\n' + full_txt
                    self.app.after(0,lambda r=rec,t=txt: on_complete(r,t))
                except Exception as exc:
                    self.app.after(0,lambda e=str(exc): on_error(e))
            threading.Thread(target=worker,daemon=True).start()

        def on_complete(rec,txt):
            self.busy=False
            for k,v in entries.items():
                v.set(str(rec.get(k,'') or '').upper() if k in ('surname','name','patronymic') else str(rec.get(k,'') or ''))
            status.set('Розпізнавання завершено. Перевір усі поля; порожні заповни вручну. Потім натисни «Готово для F7».')
            self._ocr_text=txt

        def on_error(error):
            self.busy=False
            status.set('OCR: '+error+'. Можна заповнити поля вручну.')

        def ready():
            rec={k:v.get().strip() for k,v in entries.items()}
            if not all(rec.get(k) for k in ('surname','name','patronymic','birth')):
                status.set('Для пошуку потрібні ПІБ і дата народження.')
                return
            try:
                from datetime import datetime
                datetime.strptime(rec['birth'],'%d.%m.%Y')
            except ValueError:
                status.set('Дата має бути у форматі ДД.ММ.РРРР')
                return
            self.record=rec
            self.step_index=0
            self.form_ready=True
            self.app.log('F6: дані підготовлено; клацай потрібне поле Edge і натискай F7 по одному кроку. Перший крок — Прізвище (пошук).','success')
            win.destroy()
            self._dialog=None

        ctk.CTkButton(win,text='Розпізнати текст',command=analyze,fg_color='#42647B',height=32).pack(pady=4)
        ctk.CTkButton(win,text='Підтвердити дані · F7',command=ready,fg_color='#0D9488',hover_color='#0F766E',height=34).pack(pady=4)
        win.bind('<Control-v>',paste)
        win.protocol('WM_DELETE_WINDOW',lambda: (setattr(self,'_dialog',None),win.destroy()))
        win.lift()
        win.focus_force()

    def _error(self, message):
        self.busy = False
        messagebox.showerror('F6/F7 — Воєнний злочинець', message)

    def next_step(self):
        if self.busy: return
        if not self.form_ready or not self.record:
            self.app.log('F7: спочатку натисни F6, встав скриншот і підтвердь дані.', 'warning')
            return
        if self.step_index >= len(STEP_DEFINITIONS):
            self.app.log('F7: усі значення введено. Перевір картку. УВАГА: сайт може зберігати форму після Enter.', 'success')
            return
        self.busy = True
        threading.Thread(target=self._step_worker, daemon=True).start()

    def _step_worker(self):
        index = self.step_index
        title = STEP_DEFINITIONS[index][0]
        try:
            title, value, displayed = fill_single_step(index, self.record)
            line = f'{index+1}/{len(STEP_DEFINITIONS)} | {title}: {value} | відображення: {displayed}'
            with (APP_DIR / 'F7_STEPS_LOG.txt').open('a', encoding='utf-8') as file:
                file.write(line + '\n')
            self.step_index += 1
            self.app.event_queue.put(('log', 'F7: ' + line + (' | Усі кроки завершені; перевір результат.' if self.step_index==len(STEP_DEFINITIONS) else ''), 'success'))
        except Exception as exc:
            message = f'F7 крок {index+1}/{len(STEP_DEFINITIONS)} ({title}): {exc}. Крок залишився поточним.'
            self.app.event_queue.put(('log', message, 'warning'))
            with (APP_DIR / 'F7_STEPS_LOG.txt').open('a', encoding='utf-8') as file:
                file.write('ПОМИЛКА: ' + message + '\n')
        finally:
            self.busy = False

    def calibrate(self):
        import customtkinter as ctk
        try:
            import pyautogui
        except ImportError:
            messagebox.showerror('Потрібен пакет', 'Встанови залежності з requirements.txt')
            return
        popup = ctk.CTkToplevel(self.app)
        popup.title('F6 — Налаштування полів пошуку')
        popup.geometry('550x410')
        popup.attributes('-topmost', True)
        ctk.CTkLabel(popup, text='Налаштування координат пошукової форми', font=('Segoe UI', 18, 'bold')).pack(pady=14)
        ctk.CTkLabel(popup, text='Для кожного поля: натисни кнопку, за 4 секунди\nнаведи курсор на центр поля в Edge і не рухай мишу.', justify='left').pack(pady=8)
        status = ctk.CTkLabel(popup, text='Не налаштовано')
        status.pack(pady=8)
        for key in FIELD_KEYS:
            def capture(k=key):
                status.configure(text=f'{FIELD_LABELS[k]}: наведи курсор, очікуй 4 сек…')
                def later():
                    x, y = pyautogui.position()
                    cfg = read_config()
                    cfg.setdefault('points', {})[k] = [x, y]
                    save_config(cfg)
                    status.configure(text=f'{FIELD_LABELS[k]}: збережено ({x}, {y})')
                popup.after(4000, later)
            ctk.CTkButton(popup, text='Задати: ' + FIELD_LABELS[key], command=capture).pack(pady=4)
        ctk.CTkLabel(popup, text='Для сканування екрана встанови Tesseract OCR\nз мовними пакетами російської та української.', text_color='gray').pack(pady=14)
