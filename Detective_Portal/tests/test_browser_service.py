"""Connection tests: no Chrome, driver downloads, or portal requests."""
import json
import threading
import time
from http.client import HTTPException
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from selenium.common.exceptions import WebDriverException

import browser_service as module
from browser_service import BrowserService


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def connection(monkeypatch, tmp_path):
    clock = Clock()
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(module.settings, "chrome_debug_port", 9222)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    browser = BrowserService()
    monkeypatch.setattr(browser, "CONNECT_TIMEOUT", 2.0)
    monkeypatch.setattr(browser, "find_chrome", Mock(return_value="chrome.exe"))
    ready = Mock(return_value=False)
    monkeypatch.setattr(browser, "_debugger_ready", ready)
    popen = Mock()
    popen.return_value.poll.return_value = None
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    install = Mock(return_value="chromedriver.exe")
    monkeypatch.setattr(module, "ChromeDriverManager", Mock(return_value=SimpleNamespace(install=install)))
    services = []

    def new_service(path):
        assert path == "chromedriver.exe"
        service = Mock()
        services.append(service)
        return service

    monkeypatch.setattr(module, "Service", new_service)
    driver = Mock()
    selenium = Mock(return_value=driver)
    monkeypatch.setattr(module.webdriver, "Chrome", selenium)
    return SimpleNamespace(
        browser=browser, clock=clock, ready=ready, popen=popen,
        install=install, services=services, driver=driver,
        selenium=selenium, log=Mock(), home=tmp_path,
    )


def test_fast_launch_attaches_without_fixed_sleep(connection):
    c = connection
    c.ready.side_effect = [False, True]
    c.browser.connect(c.log)
    assert c.browser.driver is c.driver
    assert c.clock.sleeps == []
    c.popen.assert_called_once_with([
        "chrome.exe", "--remote-debugging-port=9222",
        f"--user-data-dir={c.home / 'AppData/Local/DetectivePortalPro/ChromeProfile'}",
        "--no-first-run",
    ])
    c.install.assert_called_once()
    assert c.selenium.call_args.kwargs["options"].debugger_address == "127.0.0.1:9222"
    assert c.log.call_args.args[1] == "success"


def test_delayed_devtools_readiness_is_polled(connection):
    c = connection
    c.browser.CONNECT_TIMEOUT = 6.0
    c.ready.side_effect = lambda port, timeout: c.clock.now >= 4.5
    c.browser.connect(c.log)
    assert c.clock.now == 4.5
    assert c.ready.call_count > 3
    c.selenium.assert_called_once()
    c.popen.assert_called_once()
    assert any("Очікую" in call.args[0] for call in c.log.call_args_list)


def test_transient_selenium_failure_retries_same_chrome(connection):
    c = connection
    c.ready.side_effect = [False, True, True]
    error = WebDriverException("temporarily unavailable")
    c.selenium.side_effect = [error, c.driver]
    c.browser.connect(c.log)
    assert c.browser.driver is c.driver
    assert c.selenium.call_count == 2
    c.install.assert_called_once()
    c.popen.assert_called_once()
    assert len(c.services) == 2
    c.services[0].stop.assert_called_once()
    c.services[1].stop.assert_not_called()
    assert any(call.args[1] == "warning" for call in c.log.call_args_list)


def test_unavailable_port_times_out_without_selenium(connection):
    c = connection
    with pytest.raises(RuntimeError, match=r"127\.0\.0\.1:9222.*порт.*2 с") as error:
        c.browser.connect(c.log)
    assert "Підключити Chrome" in str(error.value)
    assert c.clock.now == 2.0
    assert c.browser.driver is None
    c.selenium.assert_not_called()
    c.popen.assert_called_once()
    assert all(0 < call.args[1] <= 1.0 for call in c.ready.call_args_list)


def test_permanent_selenium_failure_is_bounded_and_preserves_cause(connection):
    c = connection
    c.ready.return_value = True
    cause = WebDriverException("driver incompatible")
    c.selenium.side_effect = cause
    with pytest.raises(RuntimeError, match="Selenium не зміг приєднатися") as error:
        c.browser.connect(c.log)
    assert error.value.__cause__ is cause
    assert c.clock.now == 2.0
    assert c.selenium.call_count == 4
    assert c.browser.driver is None
    assert all(service.stop.call_count == 1 for service in c.services)
    c.popen.assert_not_called()


@pytest.mark.parametrize("first_failure", ["port", "selenium"])
def test_reconnect_after_failure_reuses_running_chrome(connection, first_failure):
    c = connection
    if first_failure == "selenium":
        c.ready.side_effect = lambda port, timeout: c.popen.called
        c.selenium.side_effect = WebDriverException("temporary failure")
    with pytest.raises(RuntimeError):
        c.browser.connect(c.log)
    c.ready.side_effect = None
    c.ready.return_value = True
    c.selenium.side_effect = None
    c.browser.connect(c.log)
    assert c.browser.driver is c.driver
    c.popen.assert_called_once()


def test_reconnect_while_chrome_still_starting_does_not_launch_again(connection):
    c = connection
    with pytest.raises(RuntimeError):
        c.browser.connect(c.log)
    c.ready.side_effect = lambda port, timeout: c.clock.now >= 3.0
    c.browser.connect(c.log)
    assert c.clock.now == 3.0
    c.popen.assert_called_once()
    assert c.browser.driver is c.driver


def test_dead_chrome_can_be_launched_on_next_connect(connection):
    c = connection
    with pytest.raises(RuntimeError):
        c.browser.connect(c.log)
    c.popen.return_value.poll.return_value = 1
    c.ready.side_effect = [False, True]
    c.browser.connect(c.log)
    assert c.popen.call_count == 2
    assert c.browser.driver is c.driver


def test_existing_debugging_chrome_needs_no_new_process(connection):
    c = connection
    c.ready.return_value = True
    c.browser.find_chrome.return_value = None
    old_driver = Mock()
    c.browser.driver = old_driver
    c.browser.connect(c.log)
    old_driver.service.stop.assert_called_once()
    old_driver.quit.assert_not_called()
    c.popen.assert_not_called()
    assert c.browser.driver is c.driver


def test_probe_time_counts_towards_deadline(connection):
    c = connection

    def slow_probe(port, timeout):
        c.clock.now += min(0.75, timeout)
        return False

    c.ready.side_effect = slow_probe
    with pytest.raises(RuntimeError):
        c.browser.connect(c.log)
    assert c.clock.now == 2.0
    c.selenium.assert_not_called()


def test_stalled_selenium_is_bounded_and_late_success_is_discarded(connection, monkeypatch):
    c = connection
    monkeypatch.setattr(module, "time", time)
    monkeypatch.setattr(c.browser, "CONNECT_TIMEOUT", 0.05)
    c.ready.return_value = True
    release = threading.Event()
    finished = threading.Event()
    stopped = threading.Event()
    late_cleanup = threading.Event()

    def stalled_constructor(*, service, options):
        def stop():
            stopped.set()
            if finished.is_set():
                late_cleanup.set()

        service.stop.side_effect = stop
        release.wait(2)
        finished.set()
        return c.driver

    c.selenium.side_effect = stalled_constructor
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="Selenium"):
            c.browser.connect(c.log)
        assert time.monotonic() - started < 1.0
        assert stopped.wait(1)
        assert c.browser.driver is None
    finally:
        release.set()
    assert finished.wait(1)
    assert late_cleanup.wait(1)
    assert c.browser.driver is None
    assert not any(call.args[1] == "success" for call in c.log.call_args_list)
    c.selenium.assert_called_once()


def test_driver_preparation_failure_is_actionable(connection):
    c = connection
    c.install.side_effect = OSError("offline")
    with pytest.raises(RuntimeError, match="підготувати ChromeDriver.*мережі"):
        c.browser.connect(c.log)
    c.popen.assert_not_called()
    c.selenium.assert_not_called()


def test_stalled_driver_preparation_is_bounded(connection, monkeypatch):
    c = connection
    monkeypatch.setattr(module, "time", time)
    monkeypatch.setattr(c.browser, "CONNECT_TIMEOUT", 0.05)
    release = threading.Event()
    finished = threading.Event()

    def slow_install():
        release.wait(2)
        finished.set()
        return "chromedriver.exe"

    c.install.side_effect = slow_install
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="підготувати ChromeDriver"):
            c.browser.connect(c.log)
        assert time.monotonic() - started < 1.0
    finally:
        release.set()
    assert finished.wait(1)
    c.popen.assert_not_called()
    c.selenium.assert_not_called()


def test_stalled_probe_is_bounded(connection, monkeypatch):
    c = connection
    monkeypatch.setattr(module, "time", time)
    monkeypatch.setattr(c.browser, "CONNECT_TIMEOUT", 0.05)
    release = threading.Event()
    c.ready.side_effect = lambda port, timeout: release.wait(2)
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="порт Chrome не готовий"):
            c.browser.connect(c.log)
        assert time.monotonic() - started < 1.0
    finally:
        release.set()
    c.selenium.assert_not_called()
    c.popen.assert_not_called()


def test_chrome_launch_failure_is_actionable(connection):
    c = connection
    c.popen.side_effect = OSError("permission denied")
    with pytest.raises(RuntimeError, match="Не вдалося запустити Google Chrome"):
        c.browser.connect(c.log)
    assert c.browser.driver is None
    c.selenium.assert_not_called()


@pytest.mark.parametrize("status,body,expected", [
    (200, {"Browser": "Chrome/130.0", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/id"}, True),
    (200, {"Browser": "Chromium/130.0", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/id"}, True),
    (503, {}, False),
    (200, {}, False),
    (200, {"Browser": "Other/1", "webSocketDebuggerUrl": "ws://localhost:9222/id"}, False),
    (200, {"Browser": "Chrome/130", "webSocketDebuggerUrl": 42}, False),
    (200, {"Browser": "Chrome/130", "webSocketDebuggerUrl": ""}, False),
    (200, [], False),
    (200, None, False),
    (200, b"not json", False),
])
def test_debugger_probe_validates_devtools_and_closes_connection(monkeypatch, status, body, expected):
    connection = MagicMock()
    connection.getresponse.return_value.status = status
    connection.getresponse.return_value.read.return_value = body if isinstance(body, bytes) else json.dumps(body).encode()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(module, "HTTPConnection", factory)
    assert BrowserService._debugger_ready(9222, 0.25) is expected
    factory.assert_called_once_with("127.0.0.1", 9222, timeout=0.25)
    connection.request.assert_called_once_with("GET", "/json/version")
    connection.close.assert_called_once()


@pytest.mark.parametrize("error", [ConnectionRefusedError(), TimeoutError(), HTTPException()])
def test_debugger_probe_treats_temporary_network_errors_as_not_ready(monkeypatch, error):
    connection = MagicMock()
    connection.request.side_effect = error
    monkeypatch.setattr(module, "HTTPConnection", Mock(return_value=connection))
    assert not BrowserService._debugger_ready(9222, 0.25)
    connection.close.assert_called_once()
