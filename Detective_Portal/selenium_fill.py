import os
import subprocess
import time
import datetime
import shutil

from tkinter import messagebox

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from excel import get_records, get_analysis_records
from openpyxl import Workbook

driver = None
current = 0
analysis_current = 0

RESULTS_ROOT = r"D:\1. Робота відділ ОЗГ\Антарес"
os.makedirs(RESULTS_ROOT, exist_ok=True)

ANALYSIS_FILE = os.path.join(RESULTS_ROOT, "analysis_all.xlsx")
analysis_results = []


def find_chrome():
    paths = [
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]

    for p in paths:
        if p and os.path.exists(p):
            return p

    return None


def connect_chrome():
    global driver

    try:
        chrome = find_chrome()

        if chrome is None:
            messagebox.showerror(
                "Помилка",
                "Google Chrome не знайдено."
            )
            return None

        profile = os.path.join(
            os.environ["TEMP"],
            "DetectivePortalChrome"
        )

        subprocess.Popen([
            chrome,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile}"
        ])

        time.sleep(4)

        options = Options()
        options.debugger_address = "127.0.0.1:9222"

        service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(
            service=service,
            options=options
        )

        return driver

    except Exception as e:
        messagebox.showerror(
            "Помилка Chrome",
            str(e)
        )
        return None


def get_inputs():
    try:
        return driver.find_elements(By.TAG_NAME, "input")
    except:
        return []


def find_field(words):
    inputs = get_inputs()

    for field in inputs:
        try:
            text = " ".join([
                field.get_attribute("placeholder") or "",
                field.get_attribute("aria-label") or "",
                field.get_attribute("name") or "",
                field.get_attribute("id") or ""
            ]).lower()

            for word in words:
                if word.lower() in text:
                    return field

        except:
            pass

    return None


def write(field, value):
    if not field:
        return False

    try:
        field.click()
        field.clear()
        field.send_keys(str(value))
        return True

    except:
        return False



def fill_birth_date(field, value):
    """Simple DevExpress date input handler."""
    try:
        # always try exact date input first
        if field is None:
            fields = driver.find_elements(
                By.CSS_SELECTOR,
                "input.dx-texteditor-input[placeholder=\"дд.мм.рррр\"]"
            )
            if not fields:
                return False
            field = fields[0]

        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});",
            field
        )
        time.sleep(0.3)

        field.click()
        time.sleep(0.2)
        field.send_keys(Keys.CONTROL + "a")
        field.send_keys(Keys.BACKSPACE)
        time.sleep(0.2)

        # real keyboard input
        field.send_keys(str(value))
        time.sleep(0.3)
        field.send_keys(Keys.TAB)
        time.sleep(0.5)

        return True

    except Exception:
        return False


def fill_next():
    global current

    records = get_records()

    if driver is None:
        return False, "Chrome не підключено"

    if current >= len(records):
        return False, "Файл закінчився"

    data = records[current]

    surname = data[0]
    name = data[1]
    father = data[2]
    birth = data[3]
    phone = data[4]
    address = data[5]

    try:
        if hasattr(birth, "strftime"):
            birth = birth.strftime("%d.%m.%Y")
        else:
            birth = datetime.datetime.strptime(
                str(birth),
                "%Y-%m-%d"
            ).strftime("%d.%m.%Y")
    except:
        birth = str(birth)

    fields = [
        (["прізвище"], surname),
        (["ім'я", "імя"], name),
        (["по батькові", "батькові"], father),
        (["дата", "народ"], birth),
        (["адреса"], address),
        (["від 9 до 13 цифр"], phone),
    ]

    found = 0

    for search, value in fields:
        field = find_field(search)

        if "дата" in search:
            ok = fill_birth_date(field, value)
        else:
            ok = write(field, value)

        if ok:
            found += 1
            time.sleep(0.2)

    try:
        save_button = driver.find_element(
            By.XPATH,
            "//span[normalize-space()='Зберегти']"
        )
        save_button.click()
        time.sleep(1)
    except:
        pass

    current += 1

    return True, {
        "current": current,
        "total": len(records),
        "found": found,
        "person": f"{surname} {name} {father}"
    }


def reset_counter():
    global current
    current = 0


def save_analysis_result(phone, rows):
    """Зберігає всі результати аналізу в один Excel файл"""
    global analysis_results

    analysis_results.append({
        "Телефон": str(phone),
        "Дата": datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "Результат": "\n".join(rows)
    })

    wb = Workbook()
    ws = wb.active
    ws.title = "Analysis"

    ws.append(["Телефон", "Дата", "Результат"])

    for item in analysis_results:
        ws.append([
            item["Телефон"],
            item["Дата"],
            item["Результат"]
        ])

    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 80

    wb.save(ANALYSIS_FILE)

    return ANALYSIS_FILE

def analyze_current_phone():

    global driver
    global analysis_current

    records = get_records()

    if driver is None:
        return False, "Chrome не підключено"

    analysis_records = get_analysis_records()
    if analysis_current >= len(analysis_records):
        return False, "Excel аналізу закінчився"

    phone = analysis_records[analysis_current]

    if not phone:
        return False, "У записі немає телефону"

    try:

        sim_input = driver.find_element(
            By.CSS_SELECTOR,
            'input[placeholder="Введіть SIM"]'
        )

        sim_input.click()
        sim_input.clear()
        sim_input.send_keys(str(phone))

        time.sleep(0.5)

        search_button = driver.find_element(
            By.CSS_SELECTOR,
            'div[aria-label="Пошук"]'
        )

        search_button.click()

        time.sleep(2)


        rows = driver.find_elements(
            By.CSS_SELECTOR,
            ".dx-datagrid-rowsview .dx-data-row"
        )

        result_rows = []

        for row in rows:
            text = row.text.strip()
            if text:
                result_rows.append(text)


        if not result_rows:
            # запасний варіант
            result_rows.append(
                driver.find_element(
                    By.TAG_NAME,
                    "body"
                ).text
            )


        saved = save_analysis_result(
            phone,
            result_rows
        )


        analysis_current += 1


        return True, {
            "phone": phone,
            "index": analysis_current,
            "total": len(analysis_records),
            "saved": saved,
            "rows": len(result_rows)
        }


    except Exception as e:
        return False, str(e)


def reset_counter():
    global current
    current = 0


