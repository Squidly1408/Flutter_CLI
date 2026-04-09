# Flutter Dev Launcher

Desktop launcher for local Flutter development workflows, built with Python and PySide6.

This tool gives you a single UI to run common Flutter automation steps, open Jira testing tickets, and perform branch-focused Git actions from one place.

## What It Does

- Run a guided Flutter workflow:
  - Stop running Dart/Flutter processes
  - Optional local database cleanup (`database/test_db1.sqlite`)
  - `flutter clean`
  - `flutter pub get`
  - `flutter pub run build_runner build --delete-conflicting-outputs`
  - `flutter gen-l10n`
  - Then either:
    - Run app (`flutter run`) or
    - Build output (`flutter build windows|apk|web`)
- Select platform target: Windows, Mobile, or Web.
- Live progress and command log with cancel support.
- Save project folder and Jira credentials via `QSettings`.
- Load Jira tickets in `Testing` status for one or more project keys.
- View ticket details, comments, and image/video attachments.
- Open ticket media in browser (with inline image preview in app).
- Git helper actions against selected project repo:
  - Checkout ticket branch
  - Checkout dev
  - Fetch current branch upstream changes
  - Pull from `origin/dev`
  - Branch picker (local + remote)
- Quick launch helpers for VS Code and GitHub Desktop.

## Tech Stack

- Python 3.10+
- PySide6 (Qt UI)
- requests (Jira REST calls)
- qtawesome (optional icon enhancement)
- PyInstaller (for packaging)

## Project Structure

```text
Flutter_CLI/
  main.py
  FlutterDevLauncher.spec
  assets/
    logo.ico
    logo.png
    logo.svg
```

## Prerequisites

1. Python 3.10 or newer.
2. Flutter SDK installed and available in `PATH`.
3. Git installed and available in `PATH`.
4. (Optional) VS Code command-line launcher `code` in `PATH`.
5. (Optional) Jira Cloud account + API token for ticket features.

On Windows, if Flutter is not in `PATH`, the app also checks `FLUTTER_ROOT` or `FLUTTER_HOME`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install PySide6 requests qtawesome pyinstaller
```

## Run Locally

```powershell
python main.py
```

## Jira Setup (In-App)

1. Click the gear icon in the title bar.
2. Fill in:
   - Jira URL (example: `https://your-company.atlassian.net`)
   - Jira email
   - Jira API token
   - Project keys (comma-separated, example: `IKD, CORE, MOBILE`)
3. Save settings.
4. Click `View Testing Tickets`.

## Build Executable (PyInstaller)

The project includes `FlutterDevLauncher.spec`.

```powershell
pyinstaller FlutterDevLauncher.spec
```

Expected output:

- executable under `dist/FlutterDevLauncher/`
- build artifacts under `build/FlutterDevLauncher/`

## Notes

- The app is primarily optimized for Windows workflows (uses Windows process handling and app ID setup).
- Mobile run mode uses `flutter run` with default device selection.
- Web run mode targets Chrome (`flutter run -d chrome`).
- Build mode output paths are inferred from Flutter defaults:
  - Windows: `build/windows`
  - APK: `build/app/outputs/flutter-apk`
  - Web: `build/web`

## Troubleshooting

- `Flutter executable not found`:
  - Add Flutter to `PATH`, or set `FLUTTER_ROOT`/`FLUTTER_HOME`.
- Jira requests fail:
  - Verify URL, email, API token, and project keys.
  - Ensure your Jira user has permission to view project issues.
- Git actions fail:
  - Confirm selected project folder is a valid Git repository.
  - Run `git fetch --all --prune` manually and retry.
