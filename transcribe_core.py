from __future__ import annotations

import ctypes
import datetime as _dt
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

MODELS = ("tiny", "base", "small", "medium", "large-v3")
DEVICES = ("cpu", "cuda")
WHISPER_REPOS = {name: f"Systran/faster-whisper-{name}" for name in MODELS}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = app_root()
MODELS_DIR = ROOT / "models"
WHISPER_DIR = MODELS_DIR / "whisper"
ARGOS_DIR = MODELS_DIR / "argos"
ARGOS_INSTALLED_DIR = ARGOS_DIR / "installed"
OUTPUT_DIR = ROOT / "output"
TEMP_DIR = ROOT / "temp"
LOG_DIR = ROOT / "logs"
BIN_DIR = ROOT / "bin"


class CancelledError(RuntimeError):
    """Raised when the user cancels a long-running operation."""


def check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise CancelledError("Обработка отменена пользователем.")


def ensure_directories() -> None:
    for path in (WHISPER_DIR, ARGOS_DIR, ARGOS_INSTALLED_DIR, OUTPUT_DIR, TEMP_DIR, LOG_DIR, BIN_DIR):
        path.mkdir(parents=True, exist_ok=True)
    path_entries = [str(BIN_DIR)]
    if os.name == "nt":
        site_packages = Path(sys.prefix) / "Lib" / "site-packages"
        path_entries.extend([
            str(site_packages / "nvidia" / "cublas" / "bin"),
            str(site_packages / "nvidia" / "cudnn" / "bin"),
        ])
        if hasattr(os, "add_dll_directory"):
            for directory in path_entries[1:]:
                if Path(directory).is_dir():
                    try:
                        os.add_dll_directory(directory)
                    except OSError:
                        pass
    os.environ["PATH"] = os.pathsep.join(path_entries + [os.environ.get("PATH", "")])


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_timestamp(value: str) -> float:
    hours, minutes, rest = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def write_txt(segments: list[dict], path: Path) -> None:
    path.write_text(" ".join(item["text"].strip() for item in segments if item["text"].strip()), encoding="utf-8")


def write_srt(segments: list[dict], path: Path) -> None:
    blocks = []
    for index, item in enumerate(segments, 1):
        blocks.append(f"{index}\n{format_timestamp(item['start'])} --> {format_timestamp(item['end'])}\n{item['text'].strip()}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def read_srt(path: Path) -> list[dict]:
    if not path.exists():
        return []
    blocks = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n\n")
    result = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start, end = lines[1].split(" --> ", 1)
        result.append({"start": parse_timestamp(start), "end": parse_timestamp(end), "text": " ".join(lines[2:])})
    return result


def output_paths(source: Path, target_language: str = "ru") -> dict[str, Path]:
    stem = source.stem
    return {
        "original_txt": OUTPUT_DIR / f"{stem}.original.txt",
        "original_srt": OUTPUT_DIR / f"{stem}.original.srt",
        "ru_txt": OUTPUT_DIR / f"{stem}.{target_language}.txt",
        "ru_srt": OUTPUT_DIR / f"{stem}.{target_language}.srt",
    }


def model_path(model_name: str) -> Path:
    if model_name not in MODELS:
        raise ValueError(f"Неизвестная модель Whisper: {model_name}")
    return WHISPER_DIR / model_name


def whisper_model_ready(model_name: str) -> bool:
    path = model_path(model_name)
    return path.is_dir() and (path / "config.json").exists()


def argos_model_path(source_lang: str, target_lang: str = "ru") -> Path:
    return ARGOS_DIR / f"{source_lang}-{target_lang}.argosmodel"


def argos_model_ready(source_lang: str, target_lang: str = "ru") -> bool:
    return argos_model_path(source_lang, target_lang).is_file() and argos_model_path(source_lang, target_lang).stat().st_size > 1024


def _download_to_local(url: str, destination: Path, cancel_event: threading.Event | None = None, attempts: int = 3) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        check_cancel(cancel_event)
        fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".part", dir=str(destination.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "TranscribeIt/1.0 (+https://www.argosopentech.com/)",
                    "Accept": "application/octet-stream,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response, temp_path.open("wb") as output:
                while True:
                    check_cancel(cancel_event)
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            check_cancel(cancel_event)
            os.replace(temp_path, destination)
            return
        except Exception as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            if attempt < attempts:
                import time
                time.sleep(min(2 * attempt, 5))
    raise last_error or RuntimeError(f"Не удалось скачать файл: {url}")


def ensure_whisper_model(model_name: str, progress: Callable[[str], None] | None = None, progress_value: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> Path:
    ensure_directories()
    destination = model_path(model_name)
    if whisper_model_ready(model_name):
        return destination
    if progress:
        progress(f"Скачивание модели Whisper '{model_name}' непосредственно в {destination}")
    staging = WHISPER_DIR / f".{model_name}.staging"
    try:
        check_cancel(cancel_event)
        # Download each repository file explicitly into a same-drive staging
        # directory. This avoids the portable-Windows cache stream issue.
        from huggingface_hub import HfApi, hf_hub_url
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        files = list(HfApi().list_repo_files(repo_id=WHISPER_REPOS[model_name], repo_type="model"))
        if not files:
            raise RuntimeError("Репозиторий модели не содержит файлов.")
        for index, filename in enumerate(files, 1):
            check_cancel(cancel_event)
            target = staging / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if progress:
                progress(f"Загрузка Whisper {model_name}: файл {index}/{len(files)} — {filename}")
            if progress_value:
                progress_value(5 + int(index / len(files) * 25), f"Загрузка модели: файл {index}/{len(files)}")
            _download_to_local(hf_hub_url(WHISPER_REPOS[model_name], filename, repo_type="model"), target, cancel_event)
        check_cancel(cancel_event)
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(staging, destination)
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, CancelledError):
            raise
        raise RuntimeError(f"Не удалось скачать модель Whisper '{model_name}' непосредственно в локальную папку. Проверьте интернет и свободное место. Подробности: {exc}") from exc
    if not whisper_model_ready(model_name):
        raise RuntimeError(f"Модель Whisper '{model_name}' скачалась неполностью: отсутствует config.json.")
    return destination


def ensure_argos_model(source_lang: str, target_lang: str = "ru", progress: Callable[[str], None] | None = None, cancel_event: threading.Event | None = None) -> Path:
    ensure_directories()
    if source_lang == target_lang:
        return argos_model_path(source_lang, target_lang)
    destination = argos_model_path(source_lang, target_lang)
    if argos_model_ready(source_lang, target_lang):
        return destination
    if progress:
        progress(f"Скачивание Argos Translate {source_lang} → {target_lang} непосредственно в {destination}")
    try:
        check_cancel(cancel_event)
        configure_argos_runtime()
        import argostranslate.package as package
        package.update_package_index()
        available = package.get_available_packages()
        candidate = next((item for item in available if item.from_code == source_lang and item.to_code == target_lang), None)
        if candidate is None:
            raise RuntimeError(f"Для пары языков '{source_lang}' → '{target_lang}' нет пакета Argos Translate.")
        urls: list[str] = []
        for candidate_url in [getattr(candidate, "download_url", None), getattr(candidate, "url", None), *(getattr(candidate, "links", None) or [])]:
            if candidate_url and candidate_url not in urls:
                urls.append(candidate_url)
        if source_lang == "en" and target_lang == "ru":
            fallback = "https://argos-net.com/v1/translate-en_ru-1_9.argosmodel"
            if fallback not in urls:
                urls.append(fallback)
        if not urls:
            raise RuntimeError("Argos не вернул ссылку на пакет модели.")
        last_error: Exception | None = None
        for url in urls:
            try:
                if progress:
                    progress(f"Пробую источник Argos: {url}")
                _download_to_local(url, destination, cancel_event)
                if argos_model_ready(source_lang, target_lang):
                    break
            except Exception as exc:
                last_error = exc
                if progress:
                    progress(f"Источник Argos недоступен: {exc}. Пробую следующий источник...")
        else:
            raise last_error or RuntimeError("Все источники Argos недоступны.")
    except Exception as exc:
        if isinstance(exc, CancelledError):
            raise
        raise RuntimeError(f"Не удалось скачать пакет Argos Translate {source_lang} → {target_lang}. Проверьте интернет. Подробности: {exc}") from exc
    if not argos_model_ready(source_lang, target_lang):
        raise RuntimeError(f"Пакет Argos Translate {source_lang} → {target_lang} не найден после скачивания.")
    return destination


def configure_argos_runtime() -> None:
    ensure_directories()
    # Argos can optionally import Stanza, which pulls PyTorch. The local
    # CTranslate2 backend does not need it and is much safer to bundle.
    os.environ.setdefault("ARGOS_STANZA_AVAILABLE", "false")
    os.environ.setdefault("ARGOS_PACKAGE_DIR", str(ARGOS_INSTALLED_DIR))


def install_argos_model(path: Path) -> None:
    configure_argos_runtime()
    import argostranslate.package as package
    package.install_from_path(str(path))


def prepare_translation_model(source_lang: str, target_lang: str, progress: Callable[[str], None] | None = None, progress_value: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> Path:
    check_cancel(cancel_event)
    if source_lang == target_lang:
        return argos_model_path(source_lang, target_lang)
    if progress:
        progress(f"Подготовка модели перевода {source_lang} → {target_lang} до начала транскрибации...")
    if progress_value:
        progress_value(30, f"Подготовка Argos: {source_lang} → {target_lang}")
    path = ensure_argos_model(source_lang, target_lang, progress, cancel_event=cancel_event)
    check_cancel(cancel_event)
    try:
        install_argos_model(path)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("torch"):
            raise RuntimeError("В сборке обнаружена несовместимая зависимость PyTorch. Удалите старые каталоги build и dist и пересоберите TranscribeIt.spec: текущая версия использует локальный CTranslate2 backend без Torch.") from exc
        raise RuntimeError(f"Не удалось установить локальную модель Argos Translate: отсутствует модуль {exc.name}.") from exc
    if progress_value:
        progress_value(35, f"Модель Argos {source_lang} → {target_lang} готова")
    return path


def detect_language(text: str) -> str:
    try:
        from langdetect import detect
        return detect(text[:10_000])
    except Exception:
        cyrillic = sum("а" <= char.lower() <= "я" for char in text)
        latin = sum("a" <= char.lower() <= "z" for char in text)
        return "ru" if cyrillic >= latin else "en"


def translate_segments(segments: list[dict], source_lang: str, target_lang: str = "ru", progress: Callable[[str], None] | None = None, progress_value: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> list[dict]:
    if source_lang == target_lang:
        return [dict(item) for item in segments]
    try:
        configure_argos_runtime()
        import argostranslate.translate as translate
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("torch"):
            raise RuntimeError("В сборке обнаружена несовместимая зависимость PyTorch. Удалите старые каталоги build и dist и пересоберите TranscribeIt.spec: текущая версия использует локальный CTranslate2 backend без Torch.") from exc
        raise RuntimeError(f"Не удалось загрузить Argos Translate: отсутствует модуль {exc.name}.") from exc
    translated = []
    total = len(segments)
    for index, item in enumerate(segments, 1):
        check_cancel(cancel_event)
        text = item["text"].strip()
        try:
            result = translate.translate(text, source_lang, target_lang) if text else ""
        except Exception as exc:
            raise RuntimeError(f"Ошибка перевода сегмента {index}: {exc}") from exc
        translated.append({"start": item["start"], "end": item["end"], "text": result or text})
        if progress and (index == total or index % 10 == 0):
            progress(f"Перевод сегментов: {index}/{total}")
        if progress_value:
            progress_value(75 + int(index / max(1, total) * 25), f"Перевод сегментов: {index}/{total}")
    return translated


@dataclass
class TranscriptionResult:
    source: Path
    language: str
    outputs: dict[str, Path]
    skipped_transcription: bool


def media_duration_seconds(source: Path) -> float:
    try:
        import av
        with av.open(str(source)) as container:
            return max(0.0, float(container.duration or 0) / 1_000_000)
    except Exception:
        return 0.0


def transcribe(source: Path, model_name: str = "medium", language: str | None = None, device: str = "cpu", no_translate: bool = False, target_language: str = "ru", progress: Callable[[str], None] | None = None, progress_value: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> TranscriptionResult:
    ensure_directories()
    if device == "cuda" and not cuda_available():
        raise RuntimeError("CUDA выбрана, но библиотека cublas64_12.dll не найдена или не может быть загружена. Выберите CPU или установите CUDA Runtime 12.x.")
    check_cancel(cancel_event)
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Исходный файл не найден: {source}")
    paths = output_paths(source, target_language)
    skipped = paths["original_txt"].exists() and paths["original_srt"].exists()
    if skipped:
        if progress:
            progress("Найдены готовые .original.txt и .original.srt — повторная транскрибация пропущена.")
        segments = read_srt(paths["original_srt"])
        text = paths["original_txt"].read_text(encoding="utf-8")
        detected = language or detect_language(text)
    else:
        if progress:
            progress("Подготовка: проверяю локальные модели Whisper и Argos Translate...")
        if progress_value:
            progress_value(0, "Подготовка моделей")
        local_model = ensure_whisper_model(model_name, progress, progress_value, cancel_event)
        check_cancel(cancel_event)
        try:
            from faster_whisper import WhisperModel
            compute_type = "int8" if device == "cpu" else "float16"
            whisper = WhisperModel(str(local_model), device=device, compute_type=compute_type)
            if language:
                detected = language
                if not no_translate:
                    prepare_translation_model(detected, target_language, progress, progress_value, cancel_event)
            else:
                if progress:
                    progress("Определяю язык по короткому фрагменту, чтобы заранее подготовить Argos Translate...")
                if progress_value:
                    progress_value(40, "Определение языка")
                probe_stream, info = whisper.transcribe(str(source), language=None, beam_size=1, vad_filter=True, condition_on_previous_text=False)
                next(probe_stream, None)
                detected = info.language
                if not no_translate:
                    prepare_translation_model(detected, target_language, progress, progress_value, cancel_event)
            check_cancel(cancel_event)
            if progress:
                progress("Все модели готовы. Загружаю Whisper и начинаю транскрибацию...")
            if progress_value:
                progress_value(40, "Начало транскрибации")
            stream, info = whisper.transcribe(str(source), language=detected, beam_size=5, vad_filter=True)
            detected = info.language
            duration = media_duration_seconds(source)
            segments = []
            for item in stream:
                check_cancel(cancel_event)
                segment = {"start": item.start, "end": item.end, "text": item.text}
                segments.append(segment)
                if progress:
                    progress(f"[{format_timestamp(item.end)}] {item.text.strip()}")
                if progress_value:
                    fraction = min(1.0, item.end / duration) if duration else 0.0
                    progress_value(35 + int(fraction * 40), f"Транскрибация: {format_timestamp(item.end)}")
        except Exception as exc:
            if isinstance(exc, CancelledError):
                raise
            raise RuntimeError(f"Ошибка транскрибации: {exc}") from exc
        write_txt(segments, paths["original_txt"])
        write_srt(segments, paths["original_srt"])
        if progress:
            progress(f"Оригинальная расшифровка сохранена в папке output. Язык: {detected}")
    if no_translate:
        return TranscriptionResult(source, detected, paths, skipped)
    if not paths["ru_txt"].exists() or not paths["ru_srt"].exists():
        if progress:
            progress("Транскрибация завершена. Проверяю готовность модели перевода...")
        if progress_value:
            progress_value(75, "Подготовка перевода")
        prepare_translation_model(detected, target_language, progress, progress_value, cancel_event)
        ru_segments = translate_segments(segments, detected, target_language, progress, progress_value, cancel_event)
        write_txt(ru_segments, paths["ru_txt"])
        write_srt(ru_segments, paths["ru_srt"])
    return TranscriptionResult(source, detected, paths, skipped)


def startup_model_check(model_name: str) -> tuple[bool, str]:
    ensure_directories()
    if whisper_model_ready(model_name):
        return True, f"Модель Whisper '{model_name}' готова."
    return False, f"Модель Whisper '{model_name}' отсутствует и будет скачана при запуске обработки."


def startup_argos_check(source_lang: str | None, target_lang: str = "ru") -> tuple[bool, str]:
    ensure_directories()
    if not source_lang or source_lang.lower() in {"auto", "автоопределение"}:
        installed = list(ARGOS_DIR.glob(f"*-{target_lang}.argosmodel"))
        if installed:
            return True, f"Argos Translate готов: найдено пакетов для перевода на '{target_lang}': {len(installed)}."
        return False, f"Argos Translate: исходный язык будет определён при обработке; пакет для '{target_lang}' будет проверен после определения."
    if source_lang == target_lang:
        return True, f"Argos Translate не требуется: исходный и целевой язык совпадают ('{source_lang}')."
    if argos_model_ready(source_lang, target_lang):
        return True, f"Пакет Argos Translate {source_lang} → {target_lang} готов."
    return False, f"Пакет Argos Translate {source_lang} → {target_lang} отсутствует и будет скачан до транскрибации."


def _cuda_runtime_dll_available() -> bool:
    if os.name != "nt":
        return True
    # CTranslate2 can see an NVIDIA device even when the CUDA user-mode
    # libraries needed to execute a model are absent from PATH. Check the
    # libraries that caused the Windows runtime failure before selecting CUDA.
    for dll_name in ("cublas64_12.dll", "cublas64_11.dll"):
        try:
            ctypes.WinDLL(dll_name)
            return True
        except (AttributeError, OSError):
            continue
    return False


def cuda_available() -> bool:
    try:
        if not _cuda_runtime_dll_available():
            return False
        import ctranslate2
        detector = getattr(ctranslate2, "get_cuda_device_count", None)
        return bool(detector and detector() > 0)
    except Exception:
        return False
