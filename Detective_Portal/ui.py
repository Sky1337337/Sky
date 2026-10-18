from __future__ import annotations

from collections import deque
import math
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from app_state import LOG_DIR, runtime, settings
from browser_service import browser
from excel_data import repo
from war_crime import WarCrimeController

ctk.set_default_color_theme("blue")

class DetectivePortalPro(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode(settings.appearance)
        self.title("Helper НПУ  •  Робоча панель")
        self.geometry("1000x650")
        self.minsize(940, 600)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.event_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.log_history = deque(maxlen=500)
        self.last_person = "—"
        self._configure_logger()
        self._build_ui()
        self.war_crime = WarCrimeController(self)
        self.war_crime.register_hotkey()
        self.after(100, self._drain_events)

    def _configure_logger(self) -> None:
        self.logger = logging.getLogger("DetectivePortalPro")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(LOG_DIR / f"session_{datetime.now():%Y%m%d}.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            self.logger.addHandler(handler)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = ctk.CTkFrame(self, width=194, corner_radius=0, fg_color=("#E8EEF1", "#101820"))
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=("#F2F5F7", "#151F29"))
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)
        self._build_sidebar()
        self._build_header()
        self._build_dashboard()
        self.log("Робочий простір готовий. Підключіть Chrome та виберіть Excel.")

    def _build_sidebar(self) -> None:
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=12, pady=(16, 15))
        ctk.CTkLabel(brand, text="H", width=36, height=36, corner_radius=11,
                     fg_color="#0F9D92", font=("Segoe UI", 21, "bold"), text_color="#FFFFFF").pack(side="left", padx=(0, 8))
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left")
        ctk.CTkLabel(names, text="Helper НПУ", font=("Segoe UI", 14, "bold"),
                     text_color=("#22263A", "#F5F3FF")).pack(anchor="w")
        ctk.CTkLabel(names, text="РОБОЧИЙ ПРОСТІР", font=("Segoe UI", 9, "bold"),
                     text_color="#2DD4BF").pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(self.sidebar, text="РОЗДІЛИ", font=("Segoe UI", 10, "bold"),
                     text_color="#94A3B8").pack(anchor="w", padx=16, pady=(0, 6))
        self.nav_buttons = {}
        for name, cmd in [
            ("⌂   Огляд", self.show_dashboard),
            ("▤   Завантажити Excel", self.choose_people_excel),
            ("▥   Аналіз Excel", self.choose_analysis_excel),
            ("◎   Підключити Chrome", self.connect_chrome),
            ("⚑   Картки · F6 / F7", self.show_war_crime),
            ("⚙   Налаштування", self.show_settings),
        ]:
            btn = ctk.CTkButton(self.sidebar, text=name, command=cmd, height=35, corner_radius=9,
                 anchor="w", font=("Segoe UI", 11, "bold"), fg_color="transparent",
                 hover_color=("#DDEFEA", "#253B46"), text_color=("#303248", "#E3E1F5"))
            btn.pack(fill="x", padx=9, pady=2)
            self.nav_buttons[name] = btn
        divider = ctk.CTkFrame(self.sidebar, height=1, fg_color=("#DDDCEF", "#323047"))
        divider.pack(fill="x", padx=15, pady=(16, 10))
        ctk.CTkLabel(self.sidebar, text="ПІДКЛЮЧЕННЯ", font=("Segoe UI", 10, "bold"),
                     text_color="#94A3B8").pack(anchor="w", padx=16, pady=(0, 5))
        self.side_excel = ctk.CTkLabel(self.sidebar, text="● Excel не вибрано", font=("Segoe UI", 10),
                                      anchor="w", text_color="#94A3B8")
        self.side_excel.pack(fill="x", padx=16, pady=3)
        self.side_chrome = ctk.CTkLabel(self.sidebar, text="● Chrome не підключено",
                                       font=("Segoe UI", 10), anchor="w", text_color="#94A3B8")
        self.side_chrome.pack(fill="x", padx=16, pady=3)
        ctk.CTkLabel(self.sidebar, text="F6 / F7  ·  Робота з картками\nF8  ·  Заповнити один запис",
                     font=("Segoe UI", 9), justify="left", text_color="#64748B").pack(side="bottom", anchor="w", padx=16, pady=14)
        self.bind_all("<F8>", lambda _e: self.fill_one())

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.content, height=60, corner_radius=0, fg_color=("#FFFFFF", "#182430"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(header, fg_color="transparent")
        head.grid(row=0, column=0, sticky="w", padx=17, pady=9)
        self.page_title = ctk.CTkLabel(head, text="Панель керування", font=("Segoe UI", 15, "bold"))
        self.page_title.pack(anchor="w")
        ctk.CTkLabel(head, text="Обробка даних та інструменти перевірки", font=("Segoe UI", 10),
                     text_color="#A1A1B7").pack(anchor="w", pady=(1, 0))
        self.theme_switch = ctk.CTkSwitch(header, text="Темна тема", command=self.toggle_theme,
                                           onvalue=1, offvalue=0, font=("Segoe UI", 10))
        self.theme_switch.grid(row=0, column=1, padx=16)
        self.theme_switch.select() if settings.appearance == "dark" else self.theme_switch.deselect()

    def _clear_body(self) -> ctk.CTkFrame:
        for name in ("stat_records", "stat_progress", "stat_status", "progress", "current_person", "log_box", "batch_count_entry"):
            if hasattr(self, name):
                delattr(self, name)
        for child in list(self.content.grid_slaves(row=1)):
            child.destroy()
        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=12)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(3, weight=1)
        return body

    def _card(self, parent, title: str, value: str, column: int):
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color=("#FFFFFF", "#1C2935"),
                            border_width=1, border_color=("#DCE4E8", "#304150"))
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 7, 7), pady=(0, 9))
        parent.grid_columnconfigure(column, weight=1)
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 11, "bold"), text_color="#8EA3BE").pack(anchor="w", padx=12, pady=(11, 2))
        label = ctk.CTkLabel(card, text=value, font=("Segoe UI", 20, "bold"))
        label.pack(anchor="w", padx=12, pady=(0, 10))
        return label

    def _build_dashboard(self) -> None:
        self.page_title.configure(text="Панель керування")
        body = self._clear_body()
        toolbar = ctk.CTkFrame(body, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(toolbar, text="Ваш робочий простір", font=("Segoe UI", 21, "bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(toolbar, text="01  Підключіть браузер    /    02  Виберіть Excel    /    03  Запустіть обробку",
                     font=("Segoe UI", 11), text_color=("#526575", "#9DB0BF")).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ctk.CTkButton(toolbar, text="+  Завантажити Excel", width=160, height=34,
                     fg_color="#0D9488", hover_color="#0F766E", command=self.choose_people_excel).grid(row=0, column=1, rowspan=2, padx=(12, 0))
        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew")
        self.stat_records = self._card(stats, "ЗАПИСІВ У ТАБЛИЦІ", "0", 0)
        self.stat_progress = self._card(stats, "ОБРОБЛЕНО", "0 / 0", 1)
        self.stat_status = self._card(stats, "СТАН СИСТЕМИ", "Готово", 2)
        controls = ctk.CTkFrame(body, corner_radius=12, fg_color=("#FFFFFF", "#1C2935"),
                                border_width=1, border_color=("#DCE4E8", "#304150"))
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        ctk.CTkLabel(controls, text="Обробка записів Excel", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=5, sticky="w", padx=13, pady=(11, 2))
        self.current_person = ctk.CTkLabel(controls, text=f"Поточна особа: {self.last_person}", font=("Segoe UI", 12), text_color="#8EA3BE")
        self.current_person.grid(row=1, column=0, columnspan=5, sticky="w", padx=13, pady=(0, 7))
        self.progress = ctk.CTkProgressBar(controls, height=7, progress_color="#2DD4BF")
        self.progress.grid(row=2, column=0, columnspan=5, sticky="ew", padx=13, pady=(0, 10))
        self.progress.set(0)
        buttons = [
            ("Заповнити один", self.fill_one, "#0D9488"),
            ("Запустити пакет", self.start_all, "#0D9488"),
            ("Пауза", self.toggle_pause, "#42647B"),
            ("Стоп", self.stop_all, "#9F4354"),
            ("Аналіз номера", self.analyze_one, "#42647B"),
        ]
        for i, (label, action, color) in enumerate(buttons):
            ctk.CTkButton(controls, text=label, command=action, height=32, corner_radius=8,
                          fg_color=color, hover_color=color, font=("Segoe UI", 10, "bold")).grid(
                row=3, column=i, padx=(13 if i == 0 else 3, 13 if i == 4 else 3), pady=(0, 10), sticky="ew")
            controls.grid_columnconfigure(i, weight=1)
        count_row = ctk.CTkFrame(controls, fg_color="transparent")
        count_row.grid(row=4, column=0, columnspan=5, sticky="w", padx=13, pady=(0, 10))
        ctk.CTkLabel(count_row, text="Кількість осіб:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 10))
        self.batch_count_entry = ctk.CTkEntry(count_row, width=85, placeholder_text="Усі", height=28)
        self.batch_count_entry.pack(side="left")
        ctk.CTkLabel(count_row, text="Порожньо — всі записи, що залишилися", text_color="#8EA3BE", font=("Segoe UI", 11)).pack(side="left", padx=12)
        log_card = ctk.CTkFrame(body, corner_radius=12, fg_color=("#FFFFFF", "#1C2935"),
                                border_width=1, border_color=("#DCE4E8", "#304150"))
        log_card.grid(row=3, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log_card, text="Журнал подій", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=13, pady=(9, 5))
        self.log_box = ctk.CTkTextbox(log_card, font=("Cascadia Mono", 10), corner_radius=8,
                                      wrap="word", fg_color=("#F5F8FA", "#131E28"))
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=11, pady=(0, 11))
        self.log_box.configure(state="normal")
        self.log_box.insert("end", "".join(self.log_history))
        self.log_box.configure(state="disabled")
        self._refresh_stats()

    def show_dashboard(self):
        self._build_dashboard(); self._refresh_stats()

    def show_war_crime(self):
        self.page_title.configure(text="Воєнний злочинець — F6 / F7")
        body = self._clear_body()
        panel = ctk.CTkFrame(body, corner_radius=16)
        panel.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(panel, text="F6: встав скриншот та аналіз. F7: одне поле або дія за натискання", font=("Segoe UI", 16, "bold")).pack(padx=20, pady=20)
        ctk.CTkLabel(panel, text="F6 відкриває вікно: встав скриншот Ctrl+V і перевір розпізнане.\nДалі клацай потрібне поле Edge та натискай F7. Пошук також виконується окремим F7.").pack(pady=12)
        ctk.CTkButton(panel, text="Вставити скриншот (F6)", command=self.war_crime.start).pack(pady=(5,20))

    def show_settings(self):
        self.page_title.configure(text="Налаштування")
        body = self._clear_body()
        panel = ctk.CTkFrame(body, corner_radius=16, fg_color=("#FFFFFF", "#162033"))
        panel.grid(row=0, column=0, sticky="new")
        panel.grid_columnconfigure(1, weight=1)
        fields = [("Затримка між полями, сек", str(settings.action_delay)), ("Порт Chrome", str(settings.chrome_debug_port)), ("Папка результатів", settings.result_folder)]
        self.settings_entries = []
        for row, (label, value) in enumerate(fields):
            ctk.CTkLabel(panel, text=label).grid(row=row, column=0, sticky="w", padx=20, pady=14)
            e = ctk.CTkEntry(panel); e.insert(0, value); e.grid(row=row, column=1, sticky="ew", padx=20, pady=10); self.settings_entries.append(e)
        ctk.CTkButton(panel, text="Зберегти", command=self.save_settings).grid(row=len(fields), column=1, sticky="e", padx=20, pady=20)

    def save_settings(self):
        try:
            delay = float(self.settings_entries[0].get())
            port = int(self.settings_entries[1].get())
            folder = self.settings_entries[2].get().strip()
            if not math.isfinite(delay) or delay < 0 or not 1 <= port <= 65535 or not folder:
                raise ValueError("Некоректні налаштування")
            settings.action_delay = delay
            settings.chrome_debug_port = port
            settings.result_folder = folder
            settings.save(); messagebox.showinfo("Готово", "Налаштування збережено")
        except ValueError:
            messagebox.showerror("Помилка", "Перевір числові значення")

    def toggle_theme(self):
        settings.appearance = "dark" if self.theme_switch.get() else "light"
        ctk.set_appearance_mode(settings.appearance); settings.save()

    def choose_people_excel(self):
        if runtime.running or (self.worker and self.worker.is_alive()):
            messagebox.showwarning("Триває операція", "Дочекайтеся завершення поточної операції")
            return
        path = filedialog.askopenfilename(title="Вибрати Excel", filetypes=[("Excel", "*.xlsx")])
        if not path: return
        try:
            count, warnings = repo.load_people(path)
            browser.current = 0
            self.side_excel.configure(text=f"● Excel: {count} записів", text_color="#22C55E")
            self.log(f"Завантажено {count} записів: {Path(path).name}", "success")
            for warning in warnings[:10]: self.log(warning, "warning")
            if len(warnings) > 10: self.log(f"Ще попереджень: {len(warnings)-10}", "warning")
            self._refresh_stats()
        except Exception as exc:
            messagebox.showerror("Помилка Excel", str(exc))

    def choose_analysis_excel(self):
        if runtime.running or (self.worker and self.worker.is_alive()):
            messagebox.showwarning("Триває операція", "Дочекайтеся завершення поточної операції")
            return
        path = filedialog.askopenfilename(title="Excel з номерами", filetypes=[("Excel", "*.xlsx")])
        if not path: return
        try:
            count = repo.load_analysis(path); browser.analysis_current = 0; self.log(f"Завантажено {count} номерів для аналізу", "success")
        except Exception as exc: messagebox.showerror("Помилка Excel", str(exc))

    def connect_chrome(self):
        if self.worker and self.worker.is_alive(): return
        self.stat_status.configure(text="Підключення…") if hasattr(self, "stat_status") else None
        self.worker = threading.Thread(target=self._connect_worker, daemon=True); self.worker.start()

    def _connect_worker(self):
        try:
            browser.connect(lambda msg, level="info": self.event_queue.put(("log", msg, level)))
            self.event_queue.put(("chrome", True))
        except Exception as exc:
            self.event_queue.put(("log", f"Помилка Chrome: {exc}", "error")); self.event_queue.put(("chrome", False))

    def fill_one(self):
        if runtime.running or (self.worker and self.worker.is_alive()): return
        if not repo.records: messagebox.showwarning("Немає даних", "Спочатку завантаж Excel"); return
        runtime.reset()
        runtime.running = True
        self.worker = threading.Thread(target=self._fill_one_worker, daemon=True); self.worker.start()

    def _fill_one_worker(self):
        try:
            if browser.current >= len(repo.records): raise RuntimeError("Усі записи вже оброблено")
            record = repo.records[browser.current]
            found = browser.fill_record(record, lambda m, l="info": self.event_queue.put(("log", m, l)))
            browser.current += 1
            self.event_queue.put(("filled", browser.current, len(repo.records), record.full_name, found))
        except Exception as exc:
            shot = browser.screenshot(); suffix = f"; скріншот: {shot}" if shot else ""
            self.event_queue.put(("log", f"Помилка: {exc}{suffix}", "error"))
        finally:
            runtime.running = False

    def start_all(self):
        if runtime.running or (self.worker and self.worker.is_alive()): return
        if not repo.records: messagebox.showwarning("Немає даних", "Спочатку завантаж Excel"); return
        remaining = len(repo.records) - browser.current
        if remaining <= 0:
            messagebox.showinfo("Завершено", "Усі записи з Excel вже оброблено")
            return
        if not hasattr(self, "batch_count_entry"):
            self.show_dashboard()
        value = self.batch_count_entry.get().strip()
        if value:
            if not value.isdecimal() or int(value) <= 0:
                messagebox.showwarning("Кількість", "Введи додатне ціле число або залиш поле порожнім")
                return
            if int(value) > remaining:
                messagebox.showwarning("Кількість", f"Залишилося {remaining} записів; вибери не більше {remaining}")
                return
            count = int(value)
        else:
            count = remaining
        runtime.reset(); runtime.running = True
        self.event_queue.put(("log", f"План: внести {count} осіб, починаючи з рядка {browser.current+1}", "info"))
        self.worker = threading.Thread(target=self._run_all_worker, args=(count,), daemon=True); self.worker.start()

    def _run_all_worker(self, count: int):
        processed = 0
        try:
            while processed < count and browser.current < len(repo.records) and not runtime.stop_event.is_set():
                while runtime.pause_event.is_set() and not runtime.stop_event.is_set(): time.sleep(0.1)
                if runtime.stop_event.is_set(): break
                record = repo.records[browser.current]
                found = browser.fill_record(record, lambda m, l="info": self.event_queue.put(("log", m, l)))
                browser.current += 1
                processed += 1
                self.event_queue.put(("filled", browser.current, len(repo.records), record.full_name, found))
            if not runtime.stop_event.is_set():
                self.event_queue.put(("log", f"Пакет завершено: успішно внесено {processed} осіб", "success"))
        except Exception as exc:
            shot = browser.screenshot(); self.event_queue.put(("log", f"Обробку зупинено: {exc}. Скріншот: {shot or 'не створено'}", "error"))
        finally: runtime.running = False

    def toggle_pause(self):
        if not runtime.running: return
        if runtime.pause_event.is_set(): runtime.pause_event.clear(); self.log("Продовжено", "info")
        else: runtime.pause_event.set(); self.log("Пауза", "warning")

    def stop_all(self):
        runtime.stop_event.set(); runtime.pause_event.clear(); self.log("Надіслано команду зупинки", "warning")

    def analyze_one(self):
        if runtime.running or (self.worker and self.worker.is_alive()): return
        if not repo.analysis_records: messagebox.showwarning("Немає номерів", "Завантаж Excel для аналізу"); return
        runtime.running = True
        self.worker = threading.Thread(target=self._analysis_worker, daemon=True); self.worker.start()

    def _analysis_worker(self):
        try:
            if browser.analysis_current >= len(repo.analysis_records): raise RuntimeError("Список номерів закінчився")
            phone = repo.analysis_records[browser.analysis_current]
            rows, output = browser.analyze_phone(phone); browser.analysis_current += 1
            self.event_queue.put(("log", f"Аналіз {phone}: знайдено рядків {len(rows)}; файл {output}", "success"))
        except Exception as exc: self.event_queue.put(("log", f"Помилка аналізу: {exc}", "error"))
        finally: runtime.running = False

    def _refresh_stats(self):
        if hasattr(self, "stat_records"):
            total = len(repo.records); current = browser.current
            self.stat_records.configure(text=str(total)); self.stat_progress.configure(text=f"{current} / {total}")
            self.progress.set(current / total if total else 0)

    def log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_history.append(line)
        if hasattr(self, "log_box"):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line); self.log_box.see("end")
            self.log_box.configure(state="disabled")
        getattr(self.logger, "error" if level == "error" else "warning" if level == "warning" else "info")(message)

    def _drain_events(self):
        try:
            while True:
                event = self.event_queue.get_nowait(); kind = event[0]
                if kind == "log": self.log(event[1], event[2])
                elif kind == "chrome":
                    ok = event[1]; self.side_chrome.configure(text="● Chrome підключено" if ok else "● Помилка Chrome", text_color="#22C55E" if ok else "#EF4444")
                    if hasattr(self, "stat_status"): self.stat_status.configure(text="Готово" if ok else "Помилка")
                elif kind == "filled":
                    current, total, person, found = event[1:]
                    self.last_person = person
                    if hasattr(self, "current_person"):
                        self.current_person.configure(text=f"Особа: {person}")
                    self._refresh_stats()
                    self.log(f"Запис {current}/{total}: заповнено полів {found}", "success")
        except queue.Empty: pass
        self.after(100, self._drain_events)

    def on_close(self):
        runtime.stop_event.set(); self.war_crime.unregister(); settings.save(); self.destroy()
