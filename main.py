# main.py
# Trading Advisor for Android
# Kivy, Foreground-friendly

import os
import csv
import time
import threading
from datetime import datetime, timedelta, timezone

import urllib.request
import urllib.parse
import json

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout

# ============================================================
# НАСТРОЙКИ
# ============================================================

SYMBOLS = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "AUDUSD=X": "AUDUSD",
    "NZDUSD=X": "NZDUSD",
    "USDCAD=X": "USDCAD",
    "USDCHF=X": "USDCHF",
    "USDJPY=X": "USDJPY",
}

# Открытие дневной свечи Forex по UTC (зимнее время США)
FOREX_DAY_OPEN_UTC_HOUR = 22

FILE_4H = "major_pairs_4h.csv"
FILE_1D = "major_pairs_1d.csv"

ANDROID_DOWNLOAD_DIR = "/storage/emulated/0/Download"

# ============================================================
# РАСЧЁТ ВРЕМЕНИ
# ============================================================

def get_local_offset_hours():
    """Разница между локальным временем телефона и UTC (в часах)."""
    local_now = datetime.now()
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    return round((local_now - utc_now).total_seconds() / 3600)


def calculate_start_hour():
    """Авто-расчёт часа открытия дневной свечи по локальному времени."""
    offset = get_local_offset_hours()
    return (FOREX_DAY_OPEN_UTC_HOUR + offset) % 24


def build_4h_grid(start_hour):
    """Сетка 4-часовых свечей от стартового часа."""
    return sorted([(start_hour + i * 4) % 24 for i in range(6)])


# ============================================================
# ЗАГРУЗКА ДАННЫХ (Yahoo Finance JSON API)
# ============================================================

def fetch_candles_for_symbol(symbol, interval_code, limit=100):
    """Загружает свечи. interval_code: '1d' или '4h'."""
    yahoo_interval = "1d" if interval_code == "1d" else "1h"
    range_map = {"1d": "6mo", "1h": "3mo"}
    yahoo_range = range_map[yahoo_interval]

    base_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = urllib.parse.urlencode({"interval": yahoo_interval, "range": yahoo_range})
    url = f"{base_url}?{params}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Android) TradingAdvisor/1.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    rows = []
    for i, ts in enumerate(timestamps):
        try:
            o = quote["open"][i]
            h = quote["high"][i]
            l = quote["low"][i]
            c = quote["close"][i]
            v = quote["volume"][i] if quote.get("volume") else 0
            if None in (o, h, l, c):
                continue
            rows.append({
                "dt": datetime.utcfromtimestamp(ts),
                "open": o, "high": h, "low": l, "close": c, "volume": v or 0,
            })
        except Exception:
            continue

    if interval_code == "4h":
        rows = aggregate_to_4h(rows)

    return rows[-limit:]


def aggregate_to_4h(rows_1h):
    """Собирает 4-часовые свечи из часовых."""
    if not rows_1h:
        return []
    buckets = {}
    for r in rows_1h:
        bucket_hour = (r["dt"].hour // 4) * 4
        key = r["dt"].replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
        buckets.setdefault(key, []).append(r)

    result = []
    for key in sorted(buckets.keys()):
        group = buckets[key]
        result.append({
            "dt": key,
            "open": group[0]["open"],
            "high": max(g["high"] for g in group),
            "low": min(g["low"] for g in group),
            "close": group[-1]["close"],
            "volume": sum(g["volume"] for g in group),
        })
    return result


def collect_and_save(interval_code, filepath, log_callback=None):
    """Собирает данные по всем парам и перезаписывает CSV."""
    def log(msg):
        if log_callback:
            log_callback(msg)

    log(f"Начинаю сбор {interval_code}...")
    all_rows = []

    for yf_symbol, pair_name in SYMBOLS.items():
        try:
            rows = fetch_candles_for_symbol(yf_symbol, interval_code)
            for r in rows:
                all_rows.append({
                    "Symbol": pair_name,
                    "Timeframe": interval_code.upper(),
                    "Datetime": r["dt"].strftime("%Y-%m-%d %H:%M:%S"),
                    "Open": round(r["open"], 5),
                    "High": round(r["high"], 5),
                    "Low": round(r["low"], 5),
                    "Close": round(r["close"], 5),
                    "Volume": int(r["volume"]),
                })
            log(f"  {pair_name}: {len(rows)} свечей")
        except Exception as e:
            log(f"  Ошибка {pair_name}: {e}")

    if not all_rows:
        log("Нет данных для сохранения.")
        return False

    try:
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["Symbol", "Timeframe", "Datetime", "Open", "High", "Low", "Close", "Volume"],
                delimiter=";"
            )
            writer.writeheader()
            writer.writerows(all_rows)
        log(f"Сохранено: {filepath}")
        return True
    except Exception as e:
        log(f"Ошибка сохранения файла: {e}")
        return False


# ============================================================
# ОТПРАВКА ФАЙЛА (только Android)
# ============================================================

def share_file_android(filepath):
    if platform != "android":
        return False
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        File = autoclass("java.io.File")

        activity = PythonActivity.mActivity
        f = File(filepath)
        uri = Uri.fromFile(f)

        intent = Intent(Intent.ACTION_VIEW)
        intent.setDataAndType(uri, "text/csv")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

        activity.startActivity(intent)
        return True
    except Exception as e:
        print(f"Ошибка отправки файла: {e}")
        return False


# ============================================================
# ПЛАНИРОВЩИК
# ============================================================

class Scheduler:
    def __init__(self, log_callback, settings):
        self.log = log_callback
        self.settings = settings
        self.running = False
        self.thread = None
        # Таймеры в секундах. Тикают вниз. 0 или меньше = сработало.
        self.timer_4h = 0
        self.timer_1d = 0

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.log("Планировщик запущен.")

    def stop(self):
        self.running = False
        self.log("Планировщик остановлен.")

    def _get_start_hour(self):
        if self.settings.get("auto"):
            return calculate_start_hour()
        return self.settings.get("start_hour", 0)

    def _seconds_to_next_4h(self, now):
        """Сколько секунд до следующей 4H-точки."""
        start_hour = self._get_start_hour()
        grid_4h = build_4h_grid(start_hour)
        candidates = []
        for h in grid_4h:
            c = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if c <= now:
                c += timedelta(days=1)
            candidates.append(c)
        return (min(candidates) - now).total_seconds()

    def _seconds_to_next_1d(self, now):
        """Сколько секунд до следующего наступления start_hour."""
        start_hour = self._get_start_hour()
        c = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if c <= now:
            c += timedelta(days=1)
        return (c - now).total_seconds()

    def _loop(self):
        # ========== Запуск: выставляем оба таймера ==========
        now = datetime.now()
        self.timer_4h = self._seconds_to_next_4h(now)
        self.timer_1d = self._seconds_to_next_1d(now)
        self.log(f"Таймеры: 4H={int(self.timer_4h)}с, 1D={int(self.timer_1d)}с")

        while self.running:
            try:
                # ========== Тик ==========
                tick = 5
                time.sleep(tick)

                if not self.running:
                    break

                self.timer_4h -= tick
                self.timer_1d -= tick

                # ========== Проверка таймеров ==========
                fire_4h = self.timer_4h <= 0
                fire_1d = self.timer_1d <= 0

                if not fire_4h and not fire_1d:
                    continue

                # ========== Ждём 20 сек ==========
                self.log("Таймер на нуле, жду 20 сек...")
                time.sleep(20)

                if not self.running:
                    break

                self.timer_4h -= 20
                self.timer_1d -= 20

                now = datetime.now()

                # ========== Сбор данных ==========
                if self.timer_4h <= 0:
                    path = os.path.join(self._download_dir(), FILE_4H)
                    self.log(f"[4H] Сбор в {now.strftime('%H:%M:%S')}")
                    collect_and_save("4h", path, self.log)
                    share_file_android(path)

                if self.timer_1d <= 0:
                    path = os.path.join(self._download_dir(), FILE_1D)
                    self.log(f"[1D] Сбор в {now.strftime('%H:%M:%S')}")
                    collect_and_save("1d", path, self.log)
                    share_file_android(path)

                # ========== ВСЕГДА перевыставляем ОБА таймера ==========
                now = datetime.now()
                self.timer_4h = self._seconds_to_next_4h(now)
                self.timer_1d = self._seconds_to_next_1d(now)
                self.log(f"Таймеры обновлены: 4H={int(self.timer_4h)}с, 1D={int(self.timer_1d)}с")

            except Exception as e:
                self.log(f"Ошибка планировщика: {e}")
                time.sleep(60)

    def _download_dir(self):
        if platform == "android":
            if not os.path.exists(ANDROID_DOWNLOAD_DIR):
                os.makedirs(ANDROID_DOWNLOAD_DIR, exist_ok=True)
            return ANDROID_DOWNLOAD_DIR
        return os.path.dirname(os.path.abspath(__file__))


# ============================================================
# ИНТЕРФЕЙС
# ============================================================

class MainLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=15, spacing=10, **kwargs)

        self.settings = {"start_hour": calculate_start_hour(), "auto": True}
        self.scheduler = None

        self.add_widget(Label(
            text="Trading Advisor",
            size_hint_y=None, height=40,
            font_size=22, bold=True,
        ))

        auto_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=40)
        auto_box.add_widget(Label(text="Автоматический расчёт часа", size_hint_x=0.7))
        self.chk_auto = CheckBox(active=True, size_hint_x=0.3)
        self.chk_auto.bind(active=self.on_auto_change)
        auto_box.add_widget(self.chk_auto)
        self.add_widget(auto_box)

        hour_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=50)
        hour_box.add_widget(Label(text="Час открытия дневной свечи (0-23):", size_hint_x=0.7))
        self.txt_hour = TextInput(
            text=str(self.settings["start_hour"]),
            input_filter="int",
            multiline=False,
            disabled=True,
            size_hint_x=0.3,
        )
        hour_box.add_widget(self.txt_hour)
        self.add_widget(hour_box)

        self.lbl_info = Label(text=self._info_text(), size_hint_y=None, height=30)
        self.add_widget(self.lbl_info)

        btn_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=50, spacing=10)
        self.btn_start = Button(text="Запустить", background_color=(0.2, 0.7, 0.2, 1))
        self.btn_start.bind(on_press=self.on_start)
        self.btn_stop = Button(text="Остановить", background_color=(0.7, 0.2, 0.2, 1))
        self.btn_stop.bind(on_press=self.on_stop)
        self.btn_test = Button(text="Тест", background_color=(0.3, 0.3, 0.7, 1))
        self.btn_test.bind(on_press=self.on_test)
        btn_box.add_widget(self.btn_start)
        btn_box.add_widget(self.btn_stop)
        btn_box.add_widget(self.btn_test)
        self.add_widget(btn_box)

        self.add_widget(Label(text="Логи:", size_hint_y=None, height=25, bold=True))
        scroll = ScrollView()
        self.log_layout = GridLayout(cols=1, size_hint_y=None, spacing=2)
        self.log_layout.bind(minimum_height=self.log_layout.setter("height"))
        scroll.add_widget(self.log_layout)
        self.add_widget(scroll)

        self.log("Приложение запущено.")
        self.log(self._info_text())

    def _info_text(self):
        offset = get_local_offset_hours()
        start = calculate_start_hour()
        grid = build_4h_grid(start)
        return f"UTC{offset:+d}  |  старт: {start:02d}:00  |  4H: {grid}"

    @mainthread
    def log(self, message):
        ts = datetime.now().strftime("%H:%M:%S")
        lbl = Label(
            text=f"[{ts}] {message}",
            size_hint_y=None, height=22,
            halign="left", valign="middle",
        )
        lbl.bind(size=lambda s, w: setattr(s, "text_size", w))
        self.log_layout.add_widget(lbl)
        Clock.schedule_once(lambda dt: setattr(
            self.log_layout.parent, "scroll_y", 0
        ) if self.log_layout.parent else None, 0.1)

    def on_auto_change(self, checkbox, value):
        self.settings["auto"] = value
        self.txt_hour.disabled = value
        if value:
            self.settings["start_hour"] = calculate_start_hour()
            self.txt_hour.text = str(self.settings["start_hour"])
        self.lbl_info.text = self._info_text()

    def on_start(self, *args):
        if not self.settings["auto"]:
            try:
                h = int(self.txt_hour.text)
                if not (0 <= h <= 23):
                    raise ValueError
                self.settings["start_hour"] = h
            except ValueError:
                self.log("Ошибка: час должен быть от 0 до 23.")
                return

        if self.scheduler and self.scheduler.running:
            self.log("Уже запущено.")
            return

        self.scheduler = Scheduler(self.log, self.settings)
        self.scheduler.start()
        self.log("Фоновая работа запущена. Можно сворачивать приложение.")

    def on_stop(self, *args):
        if self.scheduler:
            self.scheduler.stop()
        self.log("Фоновая работа остановлена.")

    def on_test(self, *args):
        def worker():
            self.log("--- ТЕСТ ---")
            base = self.scheduler._download_dir() if self.scheduler else self._fallback_dir()
            collect_and_save("4h", os.path.join(base, FILE_4H), self.log)
            collect_and_save("1d", os.path.join(base, FILE_1D), self.log)
            self.log("--- КОНЕЦ ТЕСТА ---")
        threading.Thread(target=worker, daemon=True).start()

    def _fallback_dir(self):
        if platform == "android":
            if not os.path.exists(ANDROID_DOWNLOAD_DIR):
                os.makedirs(ANDROID_DOWNLOAD_DIR, exist_ok=True)
            return ANDROID_DOWNLOAD_DIR
        return os.path.dirname(os.path.abspath(__file__))


class TradingAdvisorApp(App):
    def build(self):
        self.title = "Trading Advisor"
        return MainLayout()

    def on_pause(self):
        # Не даём Android усыпить приложение при сворачивании
        return True

    def on_resume(self):
        pass


if __name__ == "__main__":
    TradingAdvisorApp().run()
