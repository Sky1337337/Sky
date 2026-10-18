"""Educational portal page; OCR and image matching run away from Tk's UI thread."""
from __future__ import annotations

import queue
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageGrab, ImageOps

from education import EducationBank, Match, recognize_image, parse_answer_options, find_answer_option


class EducationPage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color='transparent')
        self.bank = EducationBank()
        self.source_image = None
        self.busy = False
        self.events = queue.Queue()
        self.matches = []
        self.summary_answers = None
        self.shown = 0
        self._timer = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        ctk.CTkLabel(self, text=f'{len(self.bank.blocks)} блоків · {len(self.bank.questions)} запитання · пошук за текстом і фото',
                     anchor='w', font=('Segoe UI', 13, 'bold')).grid(row=0, column=0, sticky='ew', pady=(0, 8))
        selection = ctk.CTkFrame(self, fg_color='transparent')
        selection.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        selection.grid_columnconfigure(0, weight=1)
        self.block_choices = {'Усі блоки': None, **{title: key for key, title in self.bank.blocks.items()}}
        self.block = ctk.CTkOptionMenu(selection, values=list(self.block_choices), height=32)
        self.block.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        ctk.CTkButton(selection, text='Переглянути блок', width=150, command=self.browse).grid(row=0, column=1)
        input_card = ctk.CTkFrame(self, corner_radius=12)
        input_card.grid(row=2, column=0, sticky='ew')
        input_card.grid_columnconfigure(0, weight=1)
        self.text = ctk.CTkTextbox(input_card, height=140, wrap='word', font=('Segoe UI', 13))
        self.text.grid(row=0, column=0, sticky='ew', padx=10, pady=10)
        self.preview = ctk.CTkLabel(input_card, text='', width=110)
        self.preview.grid(row=0, column=1, padx=(0, 10))
        actions = ctk.CTkFrame(input_card, fg_color='transparent')
        actions.grid(row=1, column=0, columnspan=2, sticky='ew', padx=10, pady=(0, 10))
        for column in range(3):
            actions.grid_columnconfigure(column, weight=1)
        ctk.CTkButton(actions, text='Вставити текст', width=115, command=self.paste_text).grid(row=0, column=0, sticky='ew', padx=(0, 6), pady=(0, 6))
        self.search_button = ctk.CTkButton(actions, text='Знайти відповідь', command=self.search, fg_color='#0D9488', hover_color='#0F766E')
        self.search_button.grid(row=0, column=1, sticky='ew', padx=(0, 6), pady=(0, 6))
        ctk.CTkButton(actions, text='Скриншот · Ctrl+V', width=145, command=self.paste_image).grid(row=0, column=2, sticky='ew', pady=(0, 6))
        ctk.CTkButton(actions, text='Відкрити фото', width=115, command=self.load_image).grid(row=1, column=0, sticky='ew', padx=(0, 6))
        ctk.CTkButton(actions, text='Очистити', width=80, command=self.clear).grid(row=1, column=1, sticky='ew', padx=(0, 6))
        self.status = ctk.CTkLabel(self, text='У всіх блоках: вставте питання, щоб отримати всі різні відповіді з дужок для його повторюваних варіантів.',
                                   anchor='w', wraplength=710, justify='left', font=('Segoe UI', 11))
        self.status.grid(row=3, column=0, sticky='ew', pady=8)
        self.results = ctk.CTkScrollableFrame(self, corner_radius=12)
        self.results.grid(row=4, column=0, sticky='nsew')
        self.results.grid_columnconfigure(0, weight=1)
        self.text.bind('<Control-Return>', lambda e: self.search())
        self.text.bind('<Control-v>', self._paste_shortcut)
        self._timer = self.after(100, self._poll)

    def destroy(self):
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None
        super().destroy()

    def _paste_shortcut(self, _event=None):
        try:
            image = ImageGrab.grabclipboard()
        except Exception:
            return None  # Preserve normal text paste when no clipboard image is available.
        if isinstance(image, Image.Image):
            self.set_image(image)
            return 'break'
        return None

    def paste_text(self):
        """Paste clipboard text explicitly, without interfering with normal Ctrl+V."""
        try:
            value = self.clipboard_get()
        except Exception:
            messagebox.showinfo('Буфер обміну', 'У буфері обміну немає тексту. Скопіюйте запитання та натисніть «Вставити текст».', parent=self)
            return
        self.text.focus_set()
        self.text.insert('insert', value)
        self.status.configure(text='Текст вставлено. Натисніть «Знайти відповідь».')

    def paste_image(self):
        try:
            image = ImageGrab.grabclipboard()
            if isinstance(image, list) and image:
                with Image.open(image[0]) as source:
                    image = source.copy()
            if not isinstance(image, Image.Image):
                raise ValueError('Скопіюйте скриншот як зображення, потім натисніть Ctrl+V. Або виберіть файл кнопкою «Відкрити фото».')
            self.set_image(image)
        except Exception as exc:
            messagebox.showinfo('Вставлення зображення', str(exc), parent=self)

    def load_image(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title='Скриншот запитання', filetypes=[('Зображення', '*.png *.jpg *.jpeg *.bmp *.webp')])
        if path:
            try:
                with Image.open(path) as image:
                    self.set_image(ImageOps.exif_transpose(image).convert('RGB'))
            except Exception as exc:
                messagebox.showerror('Не вдалося відкрити зображення', str(exc), parent=self)

    def set_image(self, image):
        if self.busy:
            return
        self.source_image = image.copy().convert('RGB')
        thumb = self.source_image.copy()
        thumb.thumbnail((110, 95))
        self.preview_image = ctk.CTkImage(thumb, size=thumb.size)
        self.preview.configure(image=self.preview_image)
        self._run(use_ocr=True)

    def clear(self):
        if self.busy:
            return
        self.source_image = None
        self.summary_answers = None
        self.preview.configure(image=None)
        self.text.delete('1.0', 'end')
        self._render([])
        self.status.configure(text='Вставте нове запитання або скриншот.')

    def browse(self):
        if self.busy:
            return
        block = self.block_choices[self.block.get()]
        self._render([Match(q, 1) for q in self.bank.questions if block is None or q.block == block])
        self.status.configure(text=f'Запитань у вибраному блоці: {len(self.matches)}. Відповіді збережено за наданими матеріалами.')

    def search(self):
        self._run(use_ocr=False)

    def _run(self, use_ocr=False):
        if self.busy:
            return
        query = self.text.get('1.0', 'end').strip()
        image = self.source_image.copy() if self.source_image is not None else None
        if not query and image is None:
            self.status.configure(text='Спочатку вставте текст запитання або зображення.')
            return
        block = self.block_choices[self.block.get()]
        self.busy = True
        self.search_button.configure(state='disabled')
        self.status.configure(text='Розпізнаю скриншот і порівнюю з базою…' if use_ocr else 'Шукаю відповідь…')
        # Snapshot all Tk state before starting the worker. No widget calls from this thread.
        def worker():
            warning = ''
            text = query
            try:
                if use_ocr:
                    try:
                        text = recognize_image(image)
                        if not text:
                            warning = 'Текст не розпізнано. Показано збіги за фото; допишіть запитання для уточнення.'
                    except Exception as exc:
                        warning = str(exc)
                        text = ''
                # Duplicate-question mode is triggered by the question text alone; the user does not need to paste options.
                summary_answers = self.bank.duplicate_parenthetical_answers(text, block=block)
                matches = [] if summary_answers else self.bank.search(text, block=block, image=image, limit=30)
                self.events.put(('result', matches, text, use_ocr, warning, summary_answers))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                self.busy = False
                self.search_button.configure(state='normal')
                if event[0] == 'error':
                    self.status.configure(text=f'Не вдалося виконати пошук: {event[1]}')
                    continue
                _, matches, text, use_ocr, warning, summary_answers = event
                if use_ocr:
                    self.text.delete('1.0', 'end')
                    self.text.insert('1.0', text)
                self.summary_answers = summary_answers or None
                # For exact duplicate questions, show only the distinct text saved
                # inside parentheses: one source answer per line, no option labels.
                matches_to_render = [] if self.summary_answers else matches
                self._render(matches_to_render, summary_answers=self.summary_answers)
                if self.summary_answers:
                    status = f'Відповідей із дужок для однакового питання: {len(self.summary_answers)}.'
                elif not matches:
                    status = 'У базі не знайдено достатніх збігів. Перевірте текст питання.'
                else:
                    status = 'Можливі збіги з локальної бази.'
                self.status.configure(text=f'{warning}\n{status}' if warning else status)
        except queue.Empty:
            pass
        self._timer = self.after(100, self._poll)

    def _render(self, matches, summary_answers=None):
        self.summary_answers = summary_answers or None
        for child in self.results.winfo_children():
            child.destroy()
        if summary_answers:
            card = ctk.CTkFrame(self.results, corner_radius=10)
            card.grid(row=0, column=0, sticky='ew', padx=4, pady=5)
            card.grid_columnconfigure(0, weight=1)
            # Deliberately render no numbers, labels, source IDs, or AI commentary.
            text = '\n'.join(summary_answers)
            ctk.CTkLabel(card, text=text, wraplength=620, justify='left', anchor='w',
                         font=('Segoe UI', 13)).grid(row=0, column=0, sticky='ew', padx=12, pady=12)
            ctk.CTkButton(card, text='Копіювати відповіді', width=150,
                          command=lambda value=text: self.copy_answer(value)).grid(row=1, column=0, sticky='w', padx=12, pady=(0, 10))
            self.matches = []
            self.shown = 0
            self.more_button = None
            return
        self.matches = matches
        self.shown = 0
        self.more_button = None
        self._show_more()

    def _show_more(self):
        if self.more_button:
            self.more_button.destroy()
        stop = min(self.shown+15, len(self.matches))
        for index in range(self.shown, stop):
            match = self.matches[index]
            q = match.question
            card = ctk.CTkFrame(self.results, corner_radius=10)
            card.grid(row=index, column=0, sticky='ew', padx=4, pady=5)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=f'{self.bank.blocks[q.block]} · №{q.number}', anchor='w',
                         font=('Segoe UI', 11, 'bold'), text_color=('#526575', '#9DB0BF')).grid(row=0, column=0, sticky='ew', padx=12, pady=(10, 4))
            ctk.CTkButton(card, text='Копіювати відповідь', width=145, height=26,
                          command=lambda answer=q.answer: self.copy_answer(answer)).grid(row=0, column=1, padx=12, pady=(10, 4))
            ctk.CTkLabel(card, text=q.question, wraplength=620, justify='left', anchor='w',
                         font=('Segoe UI', 13, 'bold')).grid(row=1, column=0, columnspan=2, sticky='ew', padx=12, pady=5)
            path = self.bank.image_path(q)
            if path:
                with Image.open(path) as source:
                    picture = source.copy()
                picture.thumbnail((440, 220))
                preview = ctk.CTkImage(picture, size=picture.size)
                label = ctk.CTkLabel(card, image=preview, text='', cursor='hand2')
                label.image = preview
                label.grid(row=3, column=0, columnspan=2, pady=(0, 10))
                label.bind('<Button-1>', lambda e, p=path: self.zoom(p))
            pasted_text = self.text.get('1.0', 'end').strip()
            options = parse_answer_options(pasted_text)
            option = find_answer_option(q.answer, options)
            if option:
                label, option_text = option
                answer_display = f'✓ Правильний варіант: {label}) {option_text}\nВідповідь з бази: {q.answer}'
            else:
                answer_display = f'Відповідь з бази: {q.answer}'
                if options:
                    answer_display += '\nВаріант не визначено однозначно — звірте відповідь вручну.'
            ctk.CTkLabel(card, text=answer_display, wraplength=620, justify='left', anchor='w',
                         text_color=('#08786D', '#5EEAD4'), font=('Segoe UI', 13)).grid(row=2, column=0, columnspan=2, sticky='ew', padx=12, pady=(6, 12))
        self.shown = stop
        if stop < len(self.matches):
            self.more_button = ctk.CTkButton(self.results, text=f'Показати ще · {stop} із {len(self.matches)}', command=self._show_more)
            self.more_button.grid(row=stop, column=0, pady=10)

    def copy_answer(self, answer):
        self.clipboard_clear()
        self.clipboard_append(answer)
        self.status.configure(text='Відповідь скопійовано.')

    def zoom(self, path):
        window = ctk.CTkToplevel(self)
        window.title('Зображення до запитання')
        with Image.open(path) as source:
            image = source.copy()
        image.thumbnail((900, 700))
        photo = ctk.CTkImage(image, size=image.size)
        label = ctk.CTkLabel(window, image=photo, text='')
        label.image = photo
        label.pack(padx=15, pady=15)
