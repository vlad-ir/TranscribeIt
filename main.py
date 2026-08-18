from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from PySide6.QtCore import QByteArray, QObject, QThread, QTimer, Qt, QUrl, Signal, Slot, QTime, QSize
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDropEvent, QIcon, QImage, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QProgressBar, QPlainTextEdit,
    QSizePolicy, QSlider, QStackedLayout, QVBoxLayout, QWidget, QCheckBox
)

from transcribe_core import CancelledError, DEVICES, MODELS, OUTPUT_DIR, ROOT, cuda_available, ensure_directories, ensure_argos_model, output_paths, read_srt, startup_argos_check, startup_model_check, transcribe


RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
SETTINGS_FILE = ROOT / "settings.json"

TRANSLATIONS = {
    "ru": {
        "window_title": "TranscribeIt — локальная транскрибация",
        "tagline": "Локальная транскрибация, перевод и субтитры",
        "drop": "Перетащите аудио или видео сюда\nили нажмите на эту область для выбора файла",
        "player": "Плеер и субтитры",
        "whisper": "Модель Whisper",
        "source": "Язык оригинала",
        "auto": "Автоопределение",
        "target": "Язык перевода",
        "device": "Устройство",
        "mode": "Режим",
        "translate": "Переводить",
        "start": "Начать обработку",
        "cancel": "Отменить обработку",
        "ready": "Готово. Модели хранятся локально в папке TranscribeIt/models.",
        "selected": "Файл выбран. Можно начинать обработку.",
        "play": "Воспроизвести",
        "pause": "Пауза",
        "stop": "Остановить",
        "choose": "Выберите аудио или видео",
        "checking": "Проверяю Whisper, Argos Translate и доступность CUDA...",
        "processing": "Подготовка к обработке...",
        "done": "Обработка завершена",
        "error": "Не удалось выполнить операцию",
        "settings": "Язык интерфейса",
        "canceling": "Отменяю обработку и удаляю временные данные...",
        "cancel_requested": "Запрошена отмена. Ожидаю завершения текущей операции...",
        "start_run": "Запуск обработки: проверяю исходный файл и локальные модели...",
        "audio_track": "Аудиодорожка",
    },
    "en": {
        "window_title": "TranscribeIt — local transcription",
        "tagline": "Local transcription, translation and subtitles",
        "drop": "Drop an audio or video file here\nor click this area to choose a file",
        "player": "Player and subtitles",
        "whisper": "Whisper model",
        "source": "Source language",
        "auto": "Auto-detect",
        "target": "Target language",
        "device": "Device",
        "mode": "Mode",
        "translate": "Translate",
        "start": "Start processing",
        "cancel": "Cancel processing",
        "ready": "Ready. Models are stored locally in the TranscribeIt/models folder.",
        "selected": "File selected. Ready to start processing.",
        "play": "Play",
        "pause": "Pause",
        "stop": "Stop",
        "choose": "Choose audio or video",
        "checking": "Checking Whisper, Argos Translate and CUDA availability...",
        "processing": "Preparing processing...",
        "done": "Processing complete",
        "error": "Operation failed",
        "settings": "Interface language",
        "canceling": "Canceling processing and removing temporary data...",
        "cancel_requested": "Cancellation requested. Waiting for the current operation to finish...",
        "start_run": "Starting processing: checking the input file and local models...",
        "audio_track": "Audio track",
    },
}


PLAY_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='#071018' d='M8 5v14l11-7z'/></svg>"""
PAUSE_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='#071018' d='M6 5h4v14H6zm8 0h4v14h-4z'/></svg>"""
STOP_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><rect x='6' y='6' width='12' height='12' rx='1' fill='#071018'/></svg>"""
START_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='#071018' d='M8 5v14l11-7z'/></svg>"""
CANCEL_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='#fff' d='M6 6h12v12H6z'/></svg>"""
VOLUME_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='#8b949e' d='M4 9v6h4l5 4V5L8 9H4zm11.5 3a3.5 3.5 0 0 0-1.5-2.87v5.74A3.5 3.5 0 0 0 15.5 12zm0-8v2.06A7.98 7.98 0 0 1 15.5 17.94V20A10 10 0 0 0 15.5 4z'/></svg>"""


def svg_icon(svg: str) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class WaveformWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(300)
        self._levels: list[float] = []
        self._progress = 0.0
        self._label_text = "Аудиодорожка"
        self.setStyleSheet("background: #070b12; border-radius: 8px;")

    def set_label(self, text: str) -> None:
        self._label_text = text
        self.update()

    def set_source(self, path: Path) -> None:
        self._levels = self._read_levels(path)
        self._progress = 0.0
        self.update()

    def set_progress(self, fraction: float) -> None:
        self._progress = max(0.0, min(1.0, fraction))
        self.update()

    def _read_levels(self, path: Path) -> list[float]:
        target_bins = 240
        try:
            import av
            import numpy as np
            levels = [0.0] * target_bins
            with av.open(str(path)) as container:
                stream = next((item for item in container.streams if item.type == "audio"), None)
                if stream is None:
                    return []
                duration = float(container.duration or 0) / 1_000_000
                if duration <= 0 and stream.duration and stream.time_base:
                    duration = float(stream.duration * stream.time_base)
                for frame in container.decode(stream):
                    samples = frame.to_ndarray()
                    peak = float(np.max(np.abs(samples)))
                    if np.issubdtype(samples.dtype, np.integer):
                        peak /= float(np.iinfo(samples.dtype).max)
                    else:
                        peak /= max(1.0, peak)
                    timestamp = float(frame.time or 0.0)
                    index = min(target_bins - 1, max(0, int(timestamp / duration * target_bins))) if duration else 0
                    levels[index] = max(levels[index], min(1.0, peak))
            return [max(0.015, level) for level in levels]
        except Exception:
            return [0.08] * target_bins

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        center = height / 2
        levels = self._levels or [0.12] * 80
        bar_width = max(2.0, width / len(levels))
        for index, level in enumerate(levels):
            x = index * bar_width
            bar_height = max(5.0, level * (height - 50))
            color = QColor("#22d3ee" if index / len(levels) <= self._progress else "#334155")
            painter.setPen(color)
            painter.setBrush(color)
            painter.drawRoundedRect(int(x), int(center - bar_height / 2), max(1, int(bar_width - 1)), int(bar_height), 2, 2)
        painter.setPen(QColor("#8b949e"))
        painter.drawText(20, 30, self._label_text)
        painter.end()


class VideoCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self._image = QImage()
        self.setStyleSheet("background: #000;")

    def _on_frame(self, frame: QVideoFrame) -> None:
        image = frame.toImage()
        if not image.isNull():
            self._image = image
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000"))
        if not self._image.isNull():
            scaled = self._image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawImage((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        painter.end()


class SubtitleVideo(QWidget):
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"}

    def __init__(self) -> None:
        super().__init__()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = VideoCanvas()
        self.waveform = WaveformWidget()
        self.subtitle = QLabel(self)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)
        self.subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.subtitle.setStyleSheet("background: rgba(0,0,0,220); color: white; padding: 8px 14px; border-radius: 8px; font-size: 18px; font-weight: 600;")
        self.subtitle.hide()
        self.player.setVideoSink(self.video.sink)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video, 0, 0)
        layout.addWidget(self.waveform, 0, 0)
        self.waveform.hide()
        self._subtitles: list[dict] = []
        self._is_audio = False
        self.player.positionChanged.connect(self._update_subtitle)

    def set_source(self, path: Path, subtitle_path: Path | None = None) -> None:
        self._is_audio = path.suffix.lower() in self.AUDIO_EXTENSIONS
        self.video.setVisible(not self._is_audio)
        self.waveform.setVisible(self._is_audio)
        if self._is_audio:
            self.waveform.set_source(path)
        self._subtitles = read_srt(subtitle_path) if subtitle_path else []
        self.subtitle.hide()
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    @Slot(int)
    def _update_subtitle(self, position_ms: int) -> None:
        seconds = position_ms / 1000
        duration = self.player.duration()
        if self._is_audio and duration:
            self.waveform.set_progress(position_ms / duration)
        surface = self.waveform if self._is_audio else self.video
        current = next((item["text"] for item in self._subtitles if item["start"] <= seconds <= item["end"]), "")
        if current:
            self.subtitle.setText(current)
            self.subtitle.setMaximumWidth(max(260, min(surface.width() - 40, 900)))
            self.subtitle.adjustSize()
            self.subtitle.setGeometry(
                max(20, (self.width() - self.subtitle.width()) // 2),
                max(20, surface.geometry().bottom() - self.subtitle.height() - 24),
                self.subtitle.width(),
                self.subtitle.height(),
            )
            self.subtitle.show()
            self.subtitle.raise_()
        else:
            self.subtitle.hide()
class Worker(QObject):
    progress = Signal(str)
    progress_value = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    canceled = Signal()

    def __init__(self, source: Path, model: str, language: str | None, target_language: str, device: str, no_translate: bool) -> None:
        super().__init__()
        self.source, self.model, self.language, self.target_language, self.device, self.no_translate = source, model, language, target_language, device, no_translate
        self.cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            result = transcribe(
                self.source,
                self.model,
                self.language,
                self.device,
                self.no_translate,
                self.target_language,
                self.progress.emit,
                self.progress_value.emit,
                self.cancel_event,
            )
            self.completed.emit(result)
        except CancelledError:
            self.canceled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()


class StartupWorker(QObject):
    progress = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, source_lang: str | None, target_lang: str, translate_enabled: bool) -> None:
        super().__init__()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.translate_enabled = translate_enabled

    @Slot()
    def run(self) -> None:
        try:
            ready, message = startup_model_check("medium")
            self.progress.emit(message)
            if not ready:
                from transcribe_core import ensure_whisper_model
                ensure_whisper_model("medium", self.progress.emit)
                self.progress.emit("Модель Whisper 'medium' готова.")
            if self.translate_enabled:
                argos_ready, argos_message = startup_argos_check(self.source_lang, self.target_lang)
                self.progress.emit(argos_message)
                if self.source_lang and self.source_lang not in {"auto", "Автоопределение"} and self.source_lang != self.target_lang and not argos_ready:
                    ensure_argos_model(self.source_lang, self.target_lang, self.progress.emit)
                    self.progress.emit(f"Пакет Argos Translate {self.source_lang} → {self.target_lang} готов.")
            else:
                self.progress.emit("Перевод отключён: проверка Argos Translate не требуется.")
            self.completed.emit("Проверка Whisper и Argos Translate завершена.")
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def _load_settings(self) -> dict:
        defaults = {"model": "medium", "source_language": "Автоопределение", "target_language": "ru", "device": "CUDA" if cuda_available() else "CPU", "translate": True, "volume": 80, "interface_language": "ru"}
        try:
            if SETTINGS_FILE.exists():
                saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    defaults.update({key: value for key, value in saved.items() if key in defaults})
        except (OSError, ValueError, TypeError):
            pass
        # A saved CUDA choice must not override the current runtime check.
        if defaults.get("device") == "CUDA" and not cuda_available():
            defaults["device"] = "CPU"
        # Accept both stable language codes and display names written by older builds.
        interface_language = str(defaults.get("interface_language", "ru")).strip().lower()
        legacy_language_names = {
            "русский": "ru",
            "russian": "ru",
            "english": "en",
            "английский": "en",
        }
        interface_language = legacy_language_names.get(interface_language, interface_language)
        defaults["interface_language"] = interface_language if interface_language in TRANSLATIONS else "ru"
        return defaults

    def _save_settings(self) -> None:
        data = {
            "model": self.model.currentText(),
            "source_language": self.source_language.currentText(),
            "target_language": self.target_language.currentText(),
            "device": self.device.currentText(),
            "translate": self.translate.isChecked(),
            "volume": self.volume.value() if hasattr(self, "volume") else int(self.settings.get("volume", 80)),
            "interface_language": self.interface_language.currentData() or self.ui_language,
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def tr(self, key: str) -> str:
        return TRANSLATIONS.get(self.ui_language, TRANSLATIONS["ru"]).get(key, key)

    def _set_combo_value(self, combo: QComboBox, value: str, fallback: str) -> None:
        index = combo.findText(value)
        combo.setCurrentIndex(index if index >= 0 else combo.findText(fallback))

    def _localize_runtime_message(self, message: str) -> str:
        if self.ui_language == "ru" or not message:
            return message
        exact = {
            "Запуск обработки: проверяю исходный файл и локальные модели...": self.tr("start_run"),
            "Отменяю обработку и удаляю временные данные...": self.tr("canceling"),
            "Запрошена отмена. Ожидаю завершения текущей операции...": self.tr("cancel_requested"),
            "Обработка отменена пользователем.": "Processing canceled by the user.",
            "Неполные результаты не сохранены.": "Incomplete results were not saved.",
            "Подготовка моделей": "Preparing models",
            "Начало транскрибации": "Starting transcription",
            "Определение языка": "Detecting language",
            "Подготовка перевода": "Preparing translation",
            "Все модели готовы. Загружаю Whisper и начинаю транскрибацию...": "All models are ready. Loading Whisper and starting transcription...",
            "Транскрибация завершена. Проверяю готовность модели перевода...": "Transcription complete. Checking translation model readiness...",
            "Перевод отключён: проверка Argos Translate не требуется.": "Translation is disabled: the Argos Translate check is not required.",
            "Ошибка. Подробности показаны в сообщении.": "Error. See the message for details.",
            "Подготовка к обработке...": self.tr("processing"),
        }
        if message in exact:
            return exact[message]
        if message.startswith("Обработка завершена. Язык: "):
            match = re.match(r"Обработка завершена\. Язык: (.+?)\. Файлы сохранены в (.+)", message)
            if match:
                return f"Processing complete. Language: {match.group(1)}. Files saved to {match.group(2)}"
        if message == "Обработка отменена. Неполные результаты не сохранены.":
            return "Processing canceled. Incomplete results were not saved."
        match = re.match(r"Транскрибация: (.+)", message)
        if match:
            return f"Transcription: {match.group(1)}"
        match = re.match(r"Перевод сегментов: (\d+)/(\d+)", message)
        if match:
            return f"Translating segments: {match.group(1)}/{match.group(2)}"
        match = re.match(r"Загрузка модели: файл (\d+)/(\d+)", message)
        if match:
            return f"Downloading model: file {match.group(1)}/{match.group(2)}"
        match = re.match(r"Загрузка Whisper (.+?): файл (\d+)/(\d+) — (.+)", message)
        if match:
            return f"Downloading Whisper {match.group(1)}: file {match.group(2)}/{match.group(3)} — {match.group(4)}"
        match = re.match(r"Оригинальная расшифровка сохранена в папке output\. Язык: (.+)", message)
        if match:
            return f"Original transcription saved to the output folder. Language: {match.group(1)}"
        match = re.match(r"Ошибка перевода сегмента (\d+): (.+)", message)
        if match:
            return f"Translation error in segment {match.group(1)}: {match.group(2)}"
        replacements = (
            ("Скачивание модели Whisper ", "Downloading Whisper model "),
            ("Скачивание Argos Translate ", "Downloading Argos Translate "),
            ("Скачивание Whisper ", "Downloading Whisper "),
            ("файл ", "file "),
            ("Подготовка модели перевода ", "Preparing translation model "),
            ("до начала транскрибации...", "before transcription starts..."),
            ("Подготовка Argos: ", "Preparing Argos: "),
            ("Модель Argos ", "Argos model "),
            (" готова", " is ready"),
            ("Пробую источник Argos: ", "Trying Argos source: "),
            ("Источник Argos недоступен: ", "Argos source unavailable: "),
            (". Пробую следующий источник...", ". Trying the next source..."),
            ("Подготовка: проверяю локальные модели Whisper и Argos Translate...", "Preparing: checking local Whisper and Argos Translate models..."),
            ("Определяю язык по короткому фрагменту, чтобы заранее подготовить Argos Translate...", "Detecting the language from a short sample to prepare Argos Translate..."),
            ("Найдены готовые .original.txt и .original.srt — повторная транскрибация пропущена.", "Existing .original.txt and .original.srt found — transcription was skipped."),
        )
        translated = message
        for source, target in replacements:
            translated = translated.replace(source, target)
        return translated

    def _localized_message(self, message: str) -> str:
        return self._localize_startup_message(self._localize_runtime_message(message))

    def _localize_startup_message(self, message: str) -> str:
        """Translate readiness messages produced by the core startup checks."""
        if self.ui_language == "ru":
            return message
        if message.startswith("Модель Whisper '") and ("готова" in message or "is ready" in message):
            model = re.search(r"'([^']+)'", message)
            return f"Whisper model '{model.group(1) if model else 'medium'}' is ready."
        if message.startswith("Модель Whisper '") and "отсутствует" in message:
            model = re.search(r"'([^']+)'", message)
            return f"Whisper model '{model.group(1) if model else 'medium'}' is missing and will be downloaded when processing starts."
        if message.startswith("Argos Translate готов: найдено пакетов"):
            count = re.search(r": (\d+)\.", message)
            return f"Argos Translate is ready: {count.group(1) if count else '0'} translation package(s) found for the selected target language."
        if message.startswith("Argos Translate: исходный язык"):
            return "Argos Translate: the source language will be detected during processing; the target-language package will be checked afterward."
        if message.startswith("Argos Translate не требуется"):
            return "Argos Translate is not required because the source and target languages are the same."
        if message.startswith("Пакет Argos Translate") and "готов" in message:
            return message.replace("Пакет Argos Translate", "Argos Translate package").replace("готов.", "is ready.")
        if message.startswith("Пакет Argos Translate") and "отсутствует" in message:
            return message.replace("Пакет Argos Translate", "Argos Translate package").replace("отсутствует и будет скачан до транскрибации.", "is missing and will be downloaded before transcription.")
        if message.startswith("Перевод отключён"):
            return "Translation is disabled: Argos Translate check is not required."
        if message.startswith("Проверка Whisper и Argos Translate завершена"):
            return "Whisper and Argos Translate check completed."
        return message

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("window_title"))
        self.header_subtitle.setText(self.tr("tagline"))
        self.interface_label.setText(self.tr("settings"))
        self.file_label.setText(self.tr("drop") if self.source is None else self.file_label.text())
        self.source_language.setItemText(0, self.tr("auto"))
        self.player_title.setText(self.tr("player"))
        if hasattr(self, "waveform"):
            self.waveform.set_label(self.tr("audio_track"))
        self.model_label.setText(self.tr("whisper"))
        self.source_label.setText(self.tr("source"))
        self.target_label.setText(self.tr("target"))
        self.device_label.setText(self.tr("device"))
        self.mode_label.setText(self.tr("mode"))
        self.translate.setText(self.tr("translate"))
        self.run_button.setText(self.tr("cancel" if self.processing else "start"))
        self.play_button.setToolTip(self.tr("pause" if self.player.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState else "play"))
        self.stop_button.setToolTip(self.tr("stop"))
        if hasattr(self, "log"):
            self.log.setPlainText("\n".join(self._localized_message(item) for item in self._raw_log_messages))
        if hasattr(self, "status"):
            self.status.setText(self._localized_message(self._raw_status_message) if self._raw_status_message else self.tr("ready"))

    def _interface_language_changed(self, value: str) -> None:
        self.ui_language = value if value in TRANSLATIONS else "ru"
        self._save_settings()
        self.retranslate_ui()

    def __init__(self) -> None:
        super().__init__()
        ensure_directories()
        self.settings = self._load_settings()
        self.ui_language = self.settings["interface_language"]
        self.setWindowTitle(self.tr("window_title"))
        self.setWindowIcon(QIcon(str(RESOURCE_ROOT / "assets" / "transcribeit.svg")))
        self.resize(1200, 820)
        self.setAcceptDrops(True)
        self.source: Path | None = None
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self._raw_log_messages: list[str] = []
        self._raw_status_message = ""
        self._build_ui()
        self.retranslate_ui()
        QTimer.singleShot(300, self._check_startup_model)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        main = QVBoxLayout(root)
        header = QHBoxLayout()
        title = QLabel("TranscribeIt")
        title.setObjectName("title")
        self.header_subtitle = QLabel(self.tr("tagline"))
        self.header_subtitle.setObjectName("muted")
        header.addWidget(title)
        header.addWidget(self.header_subtitle)
        header.addStretch()
        self.interface_language = QComboBox()
        self.interface_language.addItem("Русский", "ru")
        self.interface_language.addItem("English", "en")
        self.interface_language.setCurrentIndex(0 if self.ui_language == "ru" else 1)
        self.interface_language.currentIndexChanged.connect(lambda index: self._interface_language_changed(self.interface_language.itemData(index)))
        self.interface_label = QLabel(self.tr("settings"))
        header.addWidget(self.interface_label)
        header.addWidget(self.interface_language)
        main.addLayout(header)

        self.drop = QFrame()
        self.drop.setObjectName("drop")
        self.drop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop.mousePressEvent = lambda _event: self.choose_file()
        drop_layout = QVBoxLayout(self.drop)
        self.file_label = QLabel("Перетащите аудио или видео сюда\nили нажмите на эту область для выбора файла")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_label.setObjectName("dropLabel")
        drop_layout.addWidget(self.file_label)
        main.addWidget(self.drop)

        columns = QGridLayout()
        settings = QFrame()
        settings.setObjectName("card")
        form = QFormLayout(settings)
        self.model_label = QLabel(self.tr("whisper"))
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self._set_combo_value(self.model, self.settings["model"], "medium")
        self.source_language = QComboBox()
        self.source_language.setEditable(True)
        self.source_language.addItems([self.tr("auto"), "ru", "en", "de", "fr", "es", "it", "uk", "zh"])
        saved_source = self.settings["source_language"]
        if saved_source in {"Автоопределение", "Auto-detect", "auto"}:
            saved_source = self.tr("auto")
        self._set_combo_value(self.source_language, saved_source, self.tr("auto"))
        self.target_language = QComboBox()
        self.target_language.setEditable(True)
        self.target_language.addItems(["ru", "en", "de", "fr", "es", "it", "uk", "zh"])
        self._set_combo_value(self.target_language, self.settings["target_language"], "ru")
        self.device = QComboBox()
        self.device_label = QLabel(self.tr("device"))
        self.device.addItems(["CPU", "CUDA"])
        self._set_combo_value(self.device, self.settings["device"], "CUDA" if cuda_available() else "CPU")
        self.translate = QCheckBox(self.tr("translate"))
        self.translate.setChecked(bool(self.settings["translate"]))
        self.source_label = QLabel(self.tr("source"))
        self.target_label = QLabel(self.tr("target"))
        self.mode_label = QLabel(self.tr("mode"))
        form.addRow(self.model_label, self.model)
        form.addRow(self.source_label, self.source_language)
        form.addRow(self.target_label, self.target_language)
        form.addRow(self.device_label, self.device)
        form.addRow(self.mode_label, self.translate)
        self.run_button = QPushButton(self.tr("start"))
        self.run_button.setIcon(svg_icon(START_SVG))
        self.run_button.setIconSize(QSize(20, 20))
        self.run_button.setObjectName("startButton")
        self.run_button.clicked.connect(self.toggle_processing)
        self.run_button.setEnabled(False)
        form.addRow("", self.run_button)
        self.config_controls = [self.model, self.source_language, self.target_language, self.device, self.translate]
        for control in self.config_controls:
            if isinstance(control, QComboBox):
                control.currentTextChanged.connect(lambda _value: self._save_settings())
            else:
                control.toggled.connect(lambda _value: self._save_settings())
        self.processing = False
        columns.addWidget(settings, 0, 0)

        player_card = QFrame()
        player_card.setObjectName("card")
        player_layout = QVBoxLayout(player_card)
        self.player_title = QLabel(self.tr("player"))
        player_layout.addWidget(self.player_title)
        self.player = SubtitleVideo()
        self.player.setMinimumHeight(300)
        self.player.player.durationChanged.connect(self._duration_changed)
        self.player.player.positionChanged.connect(self._position_changed)
        self.player.player.playbackStateChanged.connect(self._update_play_icon)
        player_layout.addWidget(self.player, 1)
        controls = QHBoxLayout()
        self.play_button = QPushButton()
        self.play_button.setIcon(svg_icon(PLAY_SVG))
        self.play_button.setIconSize(QSize(26, 26))
        self.play_button.setFixedSize(46, 40)
        self.play_button.setToolTip(self.tr("play"))
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(svg_icon(STOP_SVG))
        self.stop_button.setIconSize(QSize(24, 24))
        self.stop_button.setFixedSize(46, 40)
        self.stop_button.setToolTip(self.tr("stop"))
        self.stop_button.clicked.connect(self.stop_media)
        controls.addWidget(self.stop_button)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setSingleStep(1000)
        self.seek.setPageStep(10000)
        self.seek.sliderMoved.connect(self.seek_media)
        controls.addWidget(self.seek, 1)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("muted")
        controls.addWidget(self.time_label)
        volume_icon = QLabel()
        volume_icon.setPixmap(svg_icon(VOLUME_SVG).pixmap(QSize(22, 22)))
        controls.addWidget(volume_icon)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.settings["volume"]))
        self.player.audio.setVolume(self.volume.value() / 100)
        self.volume.setFixedWidth(100)
        self.volume.valueChanged.connect(lambda value: self.player.audio.setVolume(value / 100))
        self.volume.valueChanged.connect(lambda _value: self._save_settings())
        controls.addWidget(self.volume)
        controls.addStretch()
        player_layout.addLayout(controls)
        columns.addWidget(player_card, 0, 1)
        columns.setColumnStretch(1, 1)
        main.addLayout(columns, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.hide()
        main.addWidget(self.progress)
        self.status = QLabel(self.tr("ready"))
        self.status.setObjectName("muted")
        main.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        main.addWidget(self.log)
        self.setCentralWidget(root)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("choose"), "", "Media (*.mp3 *.wav *.m4a *.flac *.mp4 *.mkv *.mov *.webm);;All files (*)")
        if path:
            self.set_source(Path(path))

    def _subtitle_for_source(self, path: Path) -> Path | None:
        target = self.target_language.currentText().strip().lower() or "ru"
        preferred = output_paths(path, target)["ru_srt"]
        if preferred.exists():
            return preferred
        translated = sorted(
            (item for item in OUTPUT_DIR.glob(f"{path.stem}.*.srt") if not item.name.endswith(".original.srt")),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if translated:
            return translated[0]
        original = output_paths(path, target)["original_srt"]
        return original if original.exists() else None

    def set_source(self, path: Path) -> None:
        self.source = path
        self.file_label.setText(f"{path.name}\n{path.parent}")
        self.run_button.setEnabled(True)
        self.player.set_source(path, self._subtitle_for_source(path))
        self.status.setText(self.tr("selected"))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.set_source(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def toggle_play(self) -> None:
        if self.player.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.player.pause()
        else:
            self.player.player.play()

    @Slot(object)
    def _update_play_icon(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setIcon(svg_icon(PAUSE_SVG if playing else PLAY_SVG))
        self.play_button.setToolTip(self.tr("pause" if playing else "play"))

    def stop_media(self) -> None:
        self.player.player.stop()
        self._update_play_icon(QMediaPlayer.PlaybackState.StoppedState)

    def _duration_changed(self, duration: int) -> None:
        self.seek.setRange(0, max(0, duration))
        self._update_time_label(self.player.player.position(), duration)

    def _position_changed(self, position: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self._update_time_label(position, self.player.player.duration())

    def seek_media(self, position: int) -> None:
        self.player.player.setPosition(position)

    def _update_time_label(self, position: int, duration: int) -> None:
        def clock(value: int) -> str:
            seconds = max(0, value // 1000)
            return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60:02d}:{seconds % 60:02d}"
        self.time_label.setText(f"{clock(position)} / {clock(duration)}")

    def _check_startup_model(self) -> None:
        self.status.setText(self.tr("checking"))
        source = self.source_language.currentText().strip()
        source = None if source in {"", "Автоопределение", "Auto-detect", "auto"} else source.lower()
        self.startup_thread = QThread(self)
        self.startup_worker = StartupWorker(source, self.target_language.currentText().strip().lower(), self.translate.isChecked())
        self.startup_worker.moveToThread(self.startup_thread)
        self.startup_thread.started.connect(self.startup_worker.run)
        self.startup_worker.progress.connect(self.append_log)
        self.startup_worker.completed.connect(self._set_status)
        self.startup_worker.failed.connect(self.show_error)
        self.startup_worker.completed.connect(self.startup_thread.quit)
        self.startup_worker.failed.connect(self.startup_thread.quit)
        self.startup_thread.finished.connect(self.startup_worker.deleteLater)
        self.startup_thread.finished.connect(self.startup_thread.deleteLater)
        self.startup_thread.start()

    def _set_status(self, message: str) -> None:
        self._raw_status_message = message
        self.status.setText(self._localized_message(message))

    def append_log(self, message: str) -> None:
        self._raw_log_messages.append(message)
        self.log.appendPlainText(self._localized_message(message))
        self._set_status(message)

    def toggle_processing(self) -> None:
        if self.processing:
            self.cancel_processing()
        else:
            self.start_processing()

    def _set_processing_button(self, active: bool) -> None:
        self.processing = active
        if active:
            self.run_button.setText(self.tr("cancel"))
            self.run_button.setIcon(svg_icon(CANCEL_SVG))
            self.run_button.setObjectName("cancelButton")
        else:
            self.run_button.setText(self.tr("start"))
            self.run_button.setIcon(svg_icon(START_SVG))
            self.run_button.setObjectName("startButton")
            self.run_button.setEnabled(self.source is not None)
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)

    def start_processing(self) -> None:
        if not self.source:
            return
        self.log.clear()
        self._raw_log_messages.clear()
        self._set_status("Подготовка к обработке...")
        self._set_processing_button(True)
        self.run_button.setEnabled(True)
        self.progress.setValue(0)
        self.progress.show()
        self.append_log("Запуск обработки: проверяю исходный файл и локальные модели...")
        lang = self.source_language.currentText().strip()
        if lang in {"Автоопределение", "Auto-detect", "auto"}:
            lang = None
        target_lang = self.target_language.currentText().strip().lower()
        device = self.device.currentText().lower()
        for control in self.config_controls:
            control.setEnabled(False)
        self.thread = QThread(self)
        self.worker = Worker(self.source, self.model.currentText(), lang, target_lang, device, not self.translate.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.append_log)
        self.worker.progress_value.connect(self.set_progress)
        self.worker.completed.connect(self.processing_done)
        self.worker.failed.connect(self.processing_failed)
        self.worker.canceled.connect(self.processing_canceled)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.canceled.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot(int, str)
    def set_progress(self, value: int, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, value)))
        localized = self._localize_startup_message(self._localize_runtime_message(message))
        self.progress.setFormat(f"%p% — {localized}")
        self._set_status(message)

    def cancel_processing(self) -> None:
        if self.worker:
            self.run_button.setEnabled(False)
            self._set_status("Отменяю обработку и удаляю временные данные...")
            self.append_log("Запрошена отмена. Ожидаю завершения текущей операции...")
            self.worker.cancel()

    @Slot(object)
    def processing_done(self, result) -> None:
        self.progress.hide()
        self._set_processing_button(False)
        for control in self.config_controls:
            control.setEnabled(True)
        self._set_status(f"Обработка завершена. Язык: {result.language}. Файлы сохранены в {OUTPUT_DIR}")
        subtitle = result.outputs["ru_srt"] if result.outputs["ru_srt"].exists() else result.outputs["original_srt"]
        self.player.set_source(result.source, subtitle)
        QMessageBox.information(self, self.tr("done"), f"Files saved to:\n{OUTPUT_DIR}" if self.ui_language == "en" else f"Готовые файлы сохранены в папку:\n{OUTPUT_DIR}")

    @Slot()
    def processing_canceled(self) -> None:
        self.progress.hide()
        self._set_processing_button(False)
        for control in self.config_controls:
            control.setEnabled(True)
        self._set_status("Обработка отменена. Неполные результаты не сохранены.")
        self.append_log("Обработка отменена пользователем.")

    @Slot(str)
    def processing_failed(self, message: str) -> None:
        self.progress.hide()
        self._set_processing_button(False)
        for control in self.config_controls:
            control.setEnabled(True)
        self.show_error(message)

    def show_error(self, message: str) -> None:
        self._set_status("Ошибка. Подробности показаны в сообщении.")
        QMessageBox.critical(self, self.tr("error"), message)

    def closeEvent(self, event) -> None:
        self._save_settings()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TranscribeIt")
    app.setWindowIcon(QIcon(str(RESOURCE_ROOT / "assets" / "transcribeit.svg")))
    app.setStyleSheet("""
      QWidget { background: #0d1117; color: #e6edf3; font-size: 14px; }
      #root { background: #0d1117; }
      #title { color: #67e8f9; font-size: 28px; font-weight: 700; }
      #muted { color: #8b949e; }
      #drop, #card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
      #drop { min-height: 90px; border: 2px dashed #3b82f6; }
      #dropLabel { color: #9ca3af; font-size: 16px; }
      QPushButton { background: #22d3ee; color: #071018; border: none; border-radius: 7px; padding: 9px 15px; font-weight: 600; }
      QPushButton:hover { background: #67e8f9; }
      QPushButton#cancelButton { background: #8f3b46; color: #fff1f2; }
      QPushButton#cancelButton:hover { background: #a84a56; }
      QPushButton:disabled { background: #334155; color: #94a3b8; }
      QComboBox, QPlainTextEdit { background: #0b1220; border: 1px solid #334155; border-radius: 6px; padding: 5px; }
      QProgressBar { border: 1px solid #334155; border-radius: 5px; text-align: center; }
      QProgressBar::chunk { background: #22d3ee; border-radius: 5px; }
    """)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
