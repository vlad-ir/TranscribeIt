# TranscribeIt — Developer Build Guide / Руководство разработчика

This document explains how to run, test, package, and publish TranscribeIt from source. It is intentionally bilingual: the Russian section comes first, followed by the English section.

---

## Русский

### 1. Назначение руководства

Это руководство предназначено для владельца GitHub-репозитория `TranscribeIt` и разработчиков, которые хотят запускать программу из исходников, создавать portable-каталоги и публиковать платформенные архивы. Конечному пользователю это руководство не требуется: ему достаточно скачать архив Release и запустить соответствующий launcher.

Проект использует Python 3.10+, PySide6, faster-whisper, CTranslate2, Argos Translate и PyAV. Torch не следует удалять из рабочего Windows runtime, если конкретная сборка или Argos-интеграция его требуют. CUDA используется только при наличии рабочего NVIDIA runtime; CPU является штатным fallback.

### 2. Клонирование репозитория

```bash
git clone https://github.com/vlad-ir/TranscribeIt.git
cd TranscribeIt
```

Рекомендуется работать в отдельной ветке и не добавлять в Git большие модели, `.runtime`, `.venv`, `output`, `temp`, `logs` или локальные кэши.

### 3. Запуск из установленного Python

Требуется Python 3.10 или новее. Создайте виртуальное окружение в корне проекта:

#### Windows PowerShell

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

#### macOS/Linux

```bash
python3.10 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python main.py
```

If your system Python cannot create a virtual environment, install the corresponding OS package, such as `python3-venv` on Debian/Ubuntu. Do not install dependencies globally unless you understand the consequences for other Python projects.

### 4. Portable launcher workflow

The platform launchers are the preferred way to prepare a user-facing local environment from the source archive:

| Platform | Launcher | Expected runtime |
|---|---|---|
| Windows | `Run_TranscribeIt_Windows.bat` | `.runtime\miniforge3` and `.venv` inside the project folder |
| macOS | `Run_TranscribeIt_macOS.command` | `.runtime/miniforge3` and `.venv` inside the project folder |
| Linux | `Run_TranscribeIt_Linux.sh` | `.runtime/miniforge3` and `.venv` inside the project folder |

The launcher downloads the architecture-specific Miniforge installer, creates a private environment, installs `requirements.txt`, creates local data folders, checks PyAV, and starts `main.py`. It should not modify the user’s system Python installation.

A clean first-run test should be performed in a new directory. If an earlier attempt was interrupted, remove only `.runtime`, `.venv`, `.cache`, and `.deps-ready*`; keep `models`, `output`, `settings.json`, and `logs` unless you intentionally want to reset user data.

### 5. Dependencies and multimedia runtime

`requirements.txt` contains the application-level dependencies. The important runtime groups are:

| Group | Purpose |
|---|---|
| `PySide6` | Qt desktop interface and multimedia controls |
| `faster-whisper` | Whisper transcription through CTranslate2 |
| `argostranslate` | Local translation packages |
| `av` | PyAV bindings and FFmpeg-backed media decoding |
| `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` | Windows CUDA user-mode libraries when CUDA is used |
| `huggingface-hub` | Downloading Whisper model files directly into `models/whisper` |
| `langdetect`, `numpy` | Language detection and waveform/data processing |

The Windows launcher uses a dependency marker version so a previously created environment can be refreshed after a dependency fix. If PyAV or CUDA errors persist, remove `.venv` and `.deps-ready*`, then run the launcher again.

### 6. CPU and CUDA behavior

At startup, TranscribeIt checks whether CTranslate2 can detect a CUDA device and whether the required Windows CUDA DLLs are loadable. A visible CUDA device alone is not sufficient: `cublas64_12.dll` and related runtime libraries must also be available. If they are not available, the application selects CPU. A manually saved CUDA setting is normalized to CPU when the current runtime cannot load CUDA.

For a clean GPU test, install a current NVIDIA driver, use the Windows launcher so the NVIDIA Python runtime packages are installed, and confirm that the UI shows `CUDA`. If the UI shows `CPU`, transcription remains supported but can be slower, especially with `medium` and `large-v3`.

### 7. Models and local storage

Whisper model files are downloaded file by file into `models/whisper/<model-name>`. Argos packages are downloaded into `models/argos` using local staging files and atomic replacement. This avoids cross-drive move failures and prevents a partial download from being treated as a valid model.

Do not commit model files to Git. For a public repository, add entries similar to the following to `.gitignore`:

```gitignore
.runtime/
.venv/
.cache/
models/*
!models/whisper/
!models/argos/
output/*
temp/*
logs/*
*.pyc
__pycache__/
```

The empty directory markers may be retained in a source archive, but downloaded models should remain outside version control.

### 8. Testing

Run the syntax check and unit tests from the project root:

```bash
python -m py_compile main.py transcribe_core.py
python -m unittest discover -q
```

The tests cover paths, timestamps, SRT parsing, output naming, model readiness, and core helper behavior. Screenshots or a successful window launch do not replace unit tests.

For a runtime smoke test, use a short local MP3 and MP4 file. Confirm that the following work: model readiness, audio waveform, video playback, seeking, SRT overlay, cancellation, output creation, settings persistence, and Russian/English UI switching.

### 9. Manual PyInstaller build for Windows

The Windows spec creates an onedir build. It deliberately keeps large runtime content outside the executable and collects required dynamic libraries for CTranslate2 and PyAV.

On Windows PowerShell:

```powershell
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
py -3.10 -m pip install --upgrade pip
py -3.10 -m pip install -r requirements.txt
py -3.10 -m PyInstaller --clean --noconfirm TranscribeIt.spec
```

The resulting portable directory is under `dist\TranscribeIt`. Create local data folders beside the executable:

```powershell
New-Item -ItemType Directory -Force `
  dist\TranscribeIt\models\whisper, `
  dist\TranscribeIt\models\argos, `
  dist\TranscribeIt\output, `
  dist\TranscribeIt\temp, `
  dist\TranscribeIt\logs, `
  dist\TranscribeIt\bin
```

Do not use `--onefile` for this project. Torch, Qt, CTranslate2, PyAV, and CUDA-related binaries make a one-file archive unnecessarily large and more fragile. The onedir layout is the intended portable Windows format.

### 10. Manual PyInstaller build on macOS/Linux

On macOS or Linux:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m PyInstaller --clean --noconfirm TranscribeIt.spec
mkdir -p dist/TranscribeIt/models/whisper \
         dist/TranscribeIt/models/argos \
         dist/TranscribeIt/output \
         dist/TranscribeIt/temp \
         dist/TranscribeIt/logs \
         dist/TranscribeIt/bin
```

Native desktop builds must be produced on the target operating system and architecture. A Windows PyInstaller build is not a macOS build, and an Intel macOS build is not an Apple Silicon build. Test the resulting application on a clean machine before publishing it.

### 11. Publishing to GitHub Releases

The repository can publish platform-specific source-plus-launcher archives through GitHub Actions. Keep the release names predictable and include checksums where possible:

```text
TranscribeIt_windows_*.zip
TranscribeIt_macos_*.tar.gz
TranscribeIt_linux_*.tar.gz
```

A release should contain the correct launcher for only its target platform. Do not put Windows `.bat`, macOS `.command`, and Linux `.sh` launchers into the same minimal user archive.

### 12. Common development failures

| Symptom | Action |
|---|---|
| `cublas64_12.dll` cannot be loaded | Remove `.venv` and `.deps-ready*`; rerun the Windows launcher; use CPU if CUDA is unavailable |
| `libavcodec` or PyAV import error | Reinstall `av` from the binary wheel; remove the local environment and rerun the launcher |
| Conda has no channels | Use the current launcher, which creates the environment with `conda-forge` explicitly |
| Model download is incomplete | Delete only the partial model directory/file and run the readiness check again |
| Argos package returns a download error | Check internet access and retry; packages are downloaded to local staging files |
| Application starts in the wrong language | Delete or edit `settings.json`, or switch the interface selector and restart |
| Settings are not writable | Move the folder to a writable directory outside protected system locations |

### 13. Security and distribution notes

The launcher downloads third-party installers and Python wheels from their public distribution sources. For controlled enterprise distribution, pin exact versions, verify checksums, host approved artifacts internally, and review all third-party licenses. Do not request or commit API keys: TranscribeIt is designed to use local models and packages.

---

## English

### 1. Purpose

This guide is for the owner of the `TranscribeIt` GitHub repository and developers who need to run, test, package, or publish the application from source. End users do not need this guide; they can download a Release archive and run the launcher for their platform.

The project uses Python 3.10+, PySide6, faster-whisper, CTranslate2, Argos Translate, and PyAV. Do not remove Torch from a working Windows runtime if a particular build or Argos integration requires it. CUDA is used only when the NVIDIA runtime is actually usable; CPU is the supported fallback.

### 2. Clone the repository

```bash
git clone https://github.com/vlad-ir/TranscribeIt.git
cd TranscribeIt
```

Work in a separate branch and do not commit large models, `.runtime`, `.venv`, `output`, `temp`, `logs`, or local caches.

### 3. Run from an existing Python installation

Python 3.10 or newer is required. Create a virtual environment in the project root.

#### Windows PowerShell

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

#### macOS/Linux

```bash
python3.10 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python main.py
```

If the system Python cannot create virtual environments, install the matching OS package, such as `python3-venv` on Debian/Ubuntu. Avoid global installation unless you understand its effect on other Python projects.

### 4. Portable launcher workflow

The platform launchers prepare a local user environment from a source archive:

| Platform | Launcher | Private runtime |
|---|---|---|
| Windows | `Run_TranscribeIt_Windows.bat` | `.runtime\miniforge3` and `.venv` inside the project folder |
| macOS | `Run_TranscribeIt_macOS.command` | `.runtime/miniforge3` and `.venv` inside the project folder |
| Linux | `Run_TranscribeIt_Linux.sh` | `.runtime/miniforge3` and `.venv` inside the project folder |

The launcher downloads the architecture-specific Miniforge installer, creates a private environment, installs `requirements.txt`, creates local data folders, checks PyAV, and starts `main.py`. It should not modify the system Python installation.

For a clean first-run test, use a new directory. If an earlier attempt was interrupted, remove only `.runtime`, `.venv`, `.cache`, and `.deps-ready*`; keep `models`, `output`, `settings.json`, and `logs` unless you intentionally want to reset user data.

### 5. Dependencies and multimedia runtime

`requirements.txt` contains the application dependencies. The main groups are:

| Group | Purpose |
|---|---|
| `PySide6` | Qt desktop UI and multimedia controls |
| `faster-whisper` | Whisper transcription through CTranslate2 |
| `argostranslate` | Local translation packages |
| `av` | PyAV bindings and FFmpeg-backed media decoding |
| `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` | Windows CUDA user-mode libraries |
| `huggingface-hub` | Direct Whisper model downloads into `models/whisper` |
| `langdetect`, `numpy` | Language detection and waveform/data processing |

The Windows launcher uses a dependency marker version so an existing environment can be refreshed after a dependency fix. If PyAV or CUDA errors remain, remove `.venv` and `.deps-ready*`, then run the launcher again.

### 6. CPU and CUDA behavior

At startup, TranscribeIt checks both CTranslate2 device detection and the required Windows CUDA DLLs. A visible NVIDIA device is not sufficient: `cublas64_12.dll` and related runtime libraries must be loadable. If they are not available, the application selects CPU. A saved CUDA setting is normalized to CPU when the current runtime cannot load CUDA.

For a clean GPU test, install a current NVIDIA driver, use the Windows launcher so the NVIDIA Python runtime packages are installed, and confirm that the UI shows `CUDA`. If the UI shows `CPU`, transcription remains supported but may be slower, especially with `medium` and `large-v3`.

### 7. Models and local storage

Whisper model files are downloaded file by file into `models/whisper/<model-name>`. Argos packages are downloaded into `models/argos` through local staging files and atomic replacement. This avoids cross-drive move failures and prevents partial downloads from being accepted as valid models.

Do not commit model files to Git. A suitable `.gitignore` includes:

```gitignore
.runtime/
.venv/
.cache/
models/*
!models/whisper/
!models/argos/
output/*
temp/*
logs/*
*.pyc
__pycache__/
```

### 8. Testing

From the project root:

```bash
python -m py_compile main.py transcribe_core.py
python -m unittest discover -q
```

The tests cover paths, timestamps, SRT parsing, output naming, model readiness, and core helpers. A successful window launch does not replace unit tests.

For a runtime smoke test, use a short MP3 and MP4 file. Verify model readiness, waveform display, video playback, seeking, SRT overlay, cancellation, output creation, settings persistence, and Russian/English UI switching.

### 9. Manual PyInstaller build on Windows

The Windows spec creates an onedir build. Large runtime content stays outside the executable, while required CTranslate2 and PyAV dynamic libraries are collected.

```powershell
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
py -3.10 -m pip install --upgrade pip
py -3.10 -m pip install -r requirements.txt
py -3.10 -m PyInstaller --clean --noconfirm TranscribeIt.spec
```

The portable directory is created under `dist\TranscribeIt`. Add the local data directories:

```powershell
New-Item -ItemType Directory -Force `
  dist\TranscribeIt\models\whisper, `
  dist\TranscribeIt\models\argos, `
  dist\TranscribeIt\output, `
  dist\TranscribeIt\temp, `
  dist\TranscribeIt\logs, `
  dist\TranscribeIt\bin
```

Do not use `--onefile`. Torch, Qt, CTranslate2, PyAV, and CUDA-related binaries make a one-file archive unnecessarily large and fragile. The onedir layout is the intended portable Windows format.

### 10. Manual PyInstaller build on macOS/Linux

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m PyInstaller --clean --noconfirm TranscribeIt.spec
mkdir -p dist/TranscribeIt/models/whisper \
         dist/TranscribeIt/models/argos \
         dist/TranscribeIt/output \
         dist/TranscribeIt/temp \
         dist/TranscribeIt/logs \
         dist/TranscribeIt/bin
```

Native desktop builds must be produced on the target OS and architecture. A Windows PyInstaller build is not a macOS build, and an Intel macOS build is not an Apple Silicon build. Test every artifact on a clean machine before publishing it.

### 11. GitHub Releases

Publish platform-specific source-plus-launcher archives through GitHub Actions. Use predictable names and checksums where possible:

```text
TranscribeIt_windows_*.zip
TranscribeIt_macos_*.tar.gz
TranscribeIt_linux_*.tar.gz
```

Each minimal user archive should contain only the launcher for its target platform. Do not include all three launchers in every platform archive.

### 12. Common failures

| Symptom | Action |
|---|---|
| `cublas64_12.dll` cannot be loaded | Remove `.venv` and `.deps-ready*`; rerun the Windows launcher; use CPU when CUDA is unavailable |
| `libavcodec` or PyAV import error | Reinstall the binary `av` wheel; remove the local environment and rerun the launcher |
| Conda has no channels | Use the current launcher, which explicitly uses `conda-forge` |
| Model download is incomplete | Delete only the partial model directory/file and rerun readiness checks |
| Argos download error | Check internet access and retry; packages use local staging files |
| Wrong interface language | Delete or edit `settings.json`, or switch the selector and restart |
| Permission errors | Move the folder to a writable location outside protected system directories |

### 13. Security and distribution

The launcher downloads third-party installers and Python wheels from public distribution sources. For enterprise distribution, pin exact versions, verify checksums, host approved artifacts internally, and review all third-party licenses. No API keys are required: TranscribeIt is designed around local models and local packages.

> The repository is available at [github.com/vlad-ir/TranscribeIt](https://github.com/vlad-ir/TranscribeIt).

## References

[1]: https://github.com/SYSTRAN/faster-whisper "faster-whisper"
[2]: https://github.com/argosopentech/argos-translate "Argos Translate"
[3]: https://doc.qt.io/qtforpython/ "Qt for Python / PySide6"
[4]: https://pyav.org/docs/stable/ "PyAV documentation"
[5]: https://docs.conda.io/projects/miniconda/en/latest/ "Conda documentation"
[6]: https://www.pyinstaller.org/ "PyInstaller"
