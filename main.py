import os
import sys
import signal
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSize, QPoint, QSettings
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl


APP_TITLE = "Flutter Dev Launcher"
WINDOW_W = 1180
WINDOW_H = 760
LEFT_PANEL_W = 360
APP_ICON_PATH = Path(__file__).parent / "assets" / "logo.png"


class Palette:
    BG = "#0a0f1c"
    BG_SOFT = "#121a2b"
    PANEL = "#10192a"
    PANEL_ALT = "#0d1422"
    BORDER = "#24324d"
    TEXT = "#edf3ff"
    MUTED = "#94a7c6"
    CYAN = "#10cfd5"
    CYAN_SOFT = "#0aa9af"
    GREEN = "#24d08a"
    YELLOW = "#f7c948"
    RED = "#ff5d73"


class CommandWorker(QThread):
    log_signal = Signal(str)
    status_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)
    launch_ready_signal = Signal()

    def __init__(
        self, project_dir: str, platform: str, build_mode: bool, clear_database: bool
    ):
        super().__init__()
        self.project_dir = Path(project_dir)
        self.platform = platform
        self.build_mode = build_mode
        self.clear_database = clear_database
        self._cancelled = False
        self._current_process = None
        self._launched_process = None
        self._flutter_cmd = None

    def cancel(self):
        self._cancelled = True
        self._kill_current_process_tree()
        self._kill_launched_process_tree()
        self.log_signal.emit("🛑 Cancel requested")

    def run(self):
        try:
            if not self.project_dir.exists():
                self.finished_signal.emit(
                    False, f"Project directory does not exist: {self.project_dir}"
                )
                return

            self._flutter_cmd = self._resolve_flutter_command()
            if not self._flutter_cmd:
                self.finished_signal.emit(
                    False,
                    "Flutter executable not found. Add Flutter to PATH or set FLUTTER_ROOT.",
                )
                return

            steps = [
                ("Stopping Dart...", ["taskkill", "/IM", "dart.exe", "/F"], False),
                (
                    "Stopping Flutter...",
                    ["taskkill", "/IM", "flutter.exe", "/F"],
                    False,
                ),
            ]

            if self.clear_database:
                steps.append(("Clearing DB...", None, False))

            steps.extend(
                [
                    ("flutter clean...", [self._flutter_cmd, "clean"], False),
                    ("pub get...", [self._flutter_cmd, "pub", "get"], False),
                    (
                        "build_runner...",
                        [
                            self._flutter_cmd,
                            "pub",
                            "run",
                            "build_runner",
                            "build",
                            "--delete-conflicting-outputs",
                        ],
                        False,
                    ),
                    ("l10n...", [self._flutter_cmd, "gen-l10n"], False),
                ]
            )

            if self.build_mode:
                if self.platform == "windows":
                    steps.append(
                        (
                            "Building Windows...",
                            [self._flutter_cmd, "build", "windows"],
                            True,
                        )
                    )
                elif self.platform == "mobile":
                    steps.append(
                        ("Building APK...", [self._flutter_cmd, "build", "apk"], True)
                    )
                else:
                    steps.append(
                        ("Building Web...", [self._flutter_cmd, "build", "web"], True)
                    )

            total_steps = len(steps)
            completed = 0

            for label, command, important in steps:
                if self._cancelled:
                    self.finished_signal.emit(False, "Cancelled")
                    return

                self.status_signal.emit(label)
                self.log_signal.emit(f">> {label}")

                if label == "Clearing DB...":
                    self._clear_database_file()
                else:
                    ok = self._run_command(command, tolerate_failure=not important)
                    if not ok and important:
                        self.finished_signal.emit(False, f"Failed at step: {label}")
                        return

                completed += 1
                self.progress_signal.emit(int((completed / total_steps) * 78))

            if self._cancelled:
                self.finished_signal.emit(False, "Cancelled")
                return

            if self.build_mode:
                self.status_signal.emit("Build complete ✅")
                self.progress_signal.emit(100)
                self.finished_signal.emit(True, self._get_build_output_path())
                return

            self.status_signal.emit("Launching app...")
            self.log_signal.emit(">> Launching Flutter app in background...")
            launched = self._launch_flutter_run_detached()
            if not launched:
                self.finished_signal.emit(False, "Flutter launch failed.")
                return

            self.launch_ready_signal.emit()
            self.progress_signal.emit(100)
            self.finished_signal.emit(True, "App started 🚀")

        except Exception as exc:
            self.finished_signal.emit(False, f"Unexpected error: {exc}")

    def _clear_database_file(self):
        db_path = self.project_dir / "database" / "test_db1.sqlite"
        if db_path.exists():
            db_path.unlink()
            self.log_signal.emit(f"Deleted database: {db_path}")
        else:
            self.log_signal.emit(f"Database file not found: {db_path}")

    def _resolve_flutter_command(self):
        candidates = ["flutter", "flutter.bat", "flutter.cmd", "flutter.exe"]
        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        flutter_root = os.environ.get("FLUTTER_ROOT") or os.environ.get("FLUTTER_HOME")
        if flutter_root:
            for name in ("flutter.bat", "flutter.cmd", "flutter.exe"):
                probe = Path(flutter_root) / "bin" / name
                if probe.exists():
                    return str(probe)

        return None

    def _run_command(self, command, tolerate_failure=False):
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            self._current_process = subprocess.Popen(
                command,
                cwd=self.project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=creationflags,
            )

            assert self._current_process.stdout is not None
            for line in self._current_process.stdout:
                if self._cancelled:
                    self._kill_current_process_tree()
                    return False
                self.log_signal.emit(line.rstrip())

            code = self._current_process.wait()
            self._current_process = None

            if code != 0:
                if (
                    len(command) >= 3
                    and command[0].lower() == "taskkill"
                    and code == 128
                ):
                    self.log_signal.emit("No matching process found to stop.")
                    return True
                self.log_signal.emit(
                    f"⚠ Command exited with code {code}: {' '.join(command)}"
                )
                return tolerate_failure
            return True
        except FileNotFoundError:
            self.log_signal.emit(f"⚠ Command not found: {command[0]}")
            return tolerate_failure
        except Exception as exc:
            self.log_signal.emit(f"⚠ Command error: {exc}")
            return tolerate_failure

    def _launch_flutter_run_detached(self):
        if not self._flutter_cmd:
            self.log_signal.emit("⚠ Flutter executable is not available.")
            return False

        if self.platform == "windows":
            command = [self._flutter_cmd, "run", "-d", "windows"]
        elif self.platform == "mobile":
            command = [self._flutter_cmd, "run"]
        else:
            command = [self._flutter_cmd, "run", "-d", "chrome"]

        try:
            if os.name == "nt":
                creationflags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                )
                self._launched_process = subprocess.Popen(
                    command,
                    cwd=self.project_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
            else:
                self._launched_process = subprocess.Popen(
                    command,
                    cwd=self.project_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            return True
        except Exception as exc:
            self.log_signal.emit(f"⚠ Launch error: {exc}")
            return False

    def _kill_launched_process_tree(self):
        if not self._launched_process:
            return

        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self._launched_process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(os.getpgid(self._launched_process.pid), signal.SIGTERM)
        except Exception:
            try:
                self._launched_process.kill()
            except Exception:
                pass
        finally:
            self._launched_process = None

    def _kill_current_process_tree(self):
        if not self._current_process:
            return

        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self._current_process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(os.getpgid(self._current_process.pid), signal.SIGTERM)
        except Exception:
            try:
                self._current_process.kill()
            except Exception:
                pass
        finally:
            self._current_process = None

    def _get_build_output_path(self):
        if self.platform == "windows":
            return str(self.project_dir / "build" / "windows")
        if self.platform == "mobile":
            return str(self.project_dir / "build" / "app" / "outputs" / "flutter-apk")
        return str(self.project_dir / "build" / "web")


class TitleBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.drag_pos = QPoint()
        self.setObjectName("TitleBar")
        self.setFixedHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 12, 10)
        layout.setSpacing(10)

        badge = QLabel("◈")
        badge.setObjectName("AccentBadge")
        badge.setFixedWidth(24)

        heading_wrap = QVBoxLayout()
        heading_wrap.setSpacing(0)

        title = QLabel(APP_TITLE)
        title.setObjectName("WindowTitle")
        subtitle = QLabel("Designer-grade Flutter build and run launcher")
        subtitle.setObjectName("WindowSubtitle")

        heading_wrap.addWidget(title)
        heading_wrap.addWidget(subtitle)

        layout.addWidget(badge)
        layout.addLayout(heading_wrap)
        layout.addStretch()

        self.min_btn = QPushButton("—")
        self.close_btn = QPushButton("✕")
        self.min_btn.setObjectName("TitleButton")
        self.close_btn.setObjectName("TitleButtonClose")
        self.min_btn.setFixedSize(38, 34)
        self.close_btn.setFixedSize(38, 34)

        self.min_btn.clicked.connect(self._minimize)
        self.close_btn.clicked.connect(self._close)

        layout.addWidget(self.min_btn)
        layout.addWidget(self.close_btn)

    def _minimize(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def _close(self):
        if self.parent_window:
            self.parent_window.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = (
                event.globalPosition().toPoint()
                - self.parent_window.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.dragging = False
        self.settings = QSettings("FlutterDevLauncher", "Launcher")
        self.project_dir = self._load_saved_project_dir()
        self.build_output_path = None

        self.setWindowTitle(APP_TITLE)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setMinimumSize(QSize(WINDOW_W, WINDOW_H))
        self.resize(WINDOW_W, WINDOW_H)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(18, 18, 18, 18)

        shell = QFrame()
        shell.setObjectName("Shell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.titlebar = TitleBar(self)
        shell_layout.addWidget(self.titlebar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 18, 18, 18)
        body_layout.setSpacing(18)

        shell_layout.addWidget(body)
        outer_layout.addWidget(shell)
        self.setCentralWidget(outer)

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        body_layout.addWidget(left_panel, 0)
        body_layout.addWidget(right_panel, 1)

        self._apply_styles()

    def _build_left_panel(self):
        scroll = QScrollArea()
        scroll.setObjectName("LeftPanelScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMinimumWidth(LEFT_PANEL_W)
        scroll.setMaximumWidth(LEFT_PANEL_W)
        scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(LEFT_PANEL_W)
        panel.setMaximumWidth(LEFT_PANEL_W)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(18)

        badge = QLabel("FLUTTER AUTOMATION")
        badge.setObjectName("MiniBadge")

        headline = QLabel("Build, clean, generate, run.")
        headline.setObjectName("Headline")
        headline.setWordWrap(True)

        copy = QLabel(
            "A desktop launcher for your Flutter workflow with clean logging, step control, cancel support, and platform targeting."
        )
        copy.setObjectName("BodyCopy")
        copy.setWordWrap(True)

        layout.addWidget(badge)
        layout.addWidget(headline)
        layout.addWidget(copy)

        project_label = QLabel()
        project_label.setObjectName("PathCard")
        project_label.setWordWrap(True)
        self.project_label = project_label
        self._refresh_project_label()
        layout.addWidget(project_label)

        self.change_project_button = QPushButton("Change project folder")
        self.change_project_button.setObjectName("SecondaryButton")
        self.change_project_button.clicked.connect(self.choose_project_dir)
        layout.addWidget(self.change_project_button)

        mode_card = QFrame()
        mode_card.setObjectName("Card")
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(16, 16, 16, 16)
        mode_layout.setSpacing(12)

        mode_title = QLabel("Mode")
        mode_title.setObjectName("SectionTitle")

        self.run_radio = QRadioButton("Run app")
        self.build_radio = QRadioButton("Build output")
        self.run_radio.setChecked(True)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.run_radio)
        self.mode_group.addButton(self.build_radio)

        mode_layout.addWidget(mode_title)
        mode_layout.addWidget(self.run_radio)
        mode_layout.addWidget(self.build_radio)
        layout.addWidget(mode_card)

        platform_card = QFrame()
        platform_card.setObjectName("Card")
        platform_layout = QVBoxLayout(platform_card)
        platform_layout.setContentsMargins(16, 16, 16, 16)
        platform_layout.setSpacing(12)

        platform_title = QLabel("Platform")
        platform_title.setObjectName("SectionTitle")

        self.windows_radio = QRadioButton("Windows")
        self.mobile_radio = QRadioButton("Mobile")
        self.web_radio = QRadioButton("Web")
        self.windows_radio.setChecked(True)

        self.platform_group = QButtonGroup(self)
        self.platform_group.addButton(self.windows_radio)
        self.platform_group.addButton(self.mobile_radio)
        self.platform_group.addButton(self.web_radio)

        platform_layout.addWidget(platform_title)
        platform_layout.addWidget(self.windows_radio)
        platform_layout.addWidget(self.mobile_radio)
        platform_layout.addWidget(self.web_radio)
        layout.addWidget(platform_card)

        options_card = QFrame()
        options_card.setObjectName("Card")
        options_layout = QVBoxLayout(options_card)
        options_layout.setContentsMargins(16, 16, 16, 16)
        options_layout.setSpacing(12)

        options_title = QLabel("Automation options")
        options_title.setObjectName("SectionTitle")

        self.clear_db_check = QCheckBox("Clear local test database before build/run")
        options_layout.addWidget(options_title)
        options_layout.addWidget(self.clear_db_check)
        layout.addWidget(options_card)

        actions = QGridLayout()
        actions.setHorizontalSpacing(10)
        actions.setVerticalSpacing(10)

        self.start_button = QPushButton("Start workflow")
        self.cancel_button = QPushButton("Cancel")
        self.open_build_button = QPushButton("Open build folder")
        self.open_build_button.setEnabled(False)

        self.start_button.setObjectName("PrimaryButton")
        self.cancel_button.setObjectName("SecondaryButton")
        self.open_build_button.setObjectName("GhostButton")

        self.start_button.clicked.connect(self.start_workflow)
        self.cancel_button.clicked.connect(self.cancel_workflow)
        self.open_build_button.clicked.connect(self.open_build_folder)

        actions.addWidget(self.start_button, 0, 0)
        actions.addWidget(self.cancel_button, 0, 1)
        actions.addWidget(self.open_build_button, 1, 0, 1, 2)

        layout.addLayout(actions)
        layout.addStretch()
        scroll.setWidget(panel)
        return scroll

    def _build_right_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.status_chip = QLabel("Idle")
        self.status_chip.setObjectName("StatusChip")

        top_row.addWidget(self.status_chip)
        top_row.addStretch()

        layout.addLayout(top_row)

        self.progress_label = QLabel("Waiting to start...")
        self.progress_label.setObjectName("ProgressLabel")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(12)
        layout.addWidget(self.progress_bar)

        log_title = QLabel("Execution log")
        log_title.setObjectName("SectionTitle")
        layout.addWidget(log_title)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        font = QFont("Consolas")
        font.setPointSize(10)
        self.log_box.setFont(font)
        layout.addWidget(self.log_box)

        footer = QLabel(
            "Made for local Flutter desktop automation • clean • run • generate • build"
        )
        footer.setObjectName("FooterCopy")
        layout.addWidget(footer)

        return panel

    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            QWidget {{
                color: {Palette.TEXT};
                font-family: Segoe UI, Inter, Arial;
                font-size: 14px;
            }}
            #Shell {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {Palette.BG}, stop:1 {Palette.BG_SOFT});
                border: 1px solid {Palette.BORDER};
                border-radius: 26px;
            }}
            #TitleBar {{
                background: rgba(255,255,255,0.02);
                border-top-left-radius: 26px;
                border-top-right-radius: 26px;
                border-bottom: 1px solid {Palette.BORDER};
            }}
            #AccentBadge {{
                color: {Palette.CYAN};
                font-size: 18px;
                font-weight: 700;
            }}
            #WindowTitle {{
                font-size: 17px;
                font-weight: 700;
                color: {Palette.TEXT};
            }}
            #WindowSubtitle {{
                font-size: 12px;
                color: {Palette.MUTED};
            }}
            #TitleButton, #TitleButtonClose {{
                border: 1px solid {Palette.BORDER};
                border-radius: 11px;
                background: {Palette.PANEL};
                color: {Palette.TEXT};
                font-size: 14px;
            }}
            #TitleButton:hover {{
                background: #17243b;
            }}
            #TitleButtonClose:hover {{
                background: #3a1721;
                border-color: #6a2636;
            }}
            #Panel {{
                background: rgba(255,255,255,0.025);
                border: 1px solid {Palette.BORDER};
                border-radius: 22px;
            }}
            #LeftPanelScroll {{
                background: transparent;
                border: none;
            }}
            #MiniBadge {{
                background: rgba(16, 207, 213, 0.12);
                color: {Palette.CYAN};
                border: 1px solid rgba(16, 207, 213, 0.28);
                border-radius: 10px;
                padding: 7px 10px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            #Headline {{
                font-size: 29px;
                font-weight: 800;
                line-height: 1.15;
            }}
            #BodyCopy {{
                color: {Palette.MUTED};
                font-size: 13px;
                line-height: 1.5;
            }}
            #PathCard {{
                background: {Palette.PANEL_ALT};
                border: 1px solid {Palette.BORDER};
                border-radius: 16px;
                padding: 14px;
                color: {Palette.MUTED};
            }}
            #Card {{
                background: {Palette.PANEL};
                border: 1px solid {Palette.BORDER};
                border-radius: 18px;
                height: fit-content;
            }}
            #SectionTitle {{
                font-size: 13px;
                font-weight: 700;
                color: {Palette.TEXT};
            }}
            QRadioButton, QCheckBox {{
                spacing: 10px;
                color: {Palette.TEXT};
            }}
            QRadioButton::indicator, QCheckBox::indicator {{
                width: 18px;
                height: 18px;
            }}
            QRadioButton::indicator {{
                border-radius: 9px;
                border: 1px solid {Palette.BORDER};
                background: {Palette.PANEL_ALT};
            }}
            QRadioButton::indicator:checked {{
                background: {Palette.CYAN};
                border: 1px solid {Palette.CYAN};
            }}
            QCheckBox::indicator {{
                border-radius: 6px;
                border: 1px solid {Palette.BORDER};
                background: {Palette.PANEL_ALT};
            }}
            QCheckBox::indicator:checked {{
                background: {Palette.CYAN};
                border: 1px solid {Palette.CYAN};
            }}
            QPushButton {{
                min-height: 44px;
                border-radius: 14px;
                padding: 0 16px;
                font-weight: 700;
                border: 1px solid {Palette.BORDER};
            }}
            #PrimaryButton {{
                background: {Palette.CYAN};
                color: #031317;
                border: none;
            }}
            #PrimaryButton:hover {{
                background: {Palette.CYAN_SOFT};
                color: white;
            }}
            #SecondaryButton {{
                background: #1a2336;
                color: {Palette.TEXT};
            }}
            #SecondaryButton:hover, #GhostButton:hover {{
                background: #202d45;
            }}
            #GhostButton {{
                background: transparent;
                color: {Palette.TEXT};
            }}
            #StatusChip {{
                background: rgba(16, 207, 213, 0.10);
                color: {Palette.CYAN};
                border: 1px solid rgba(16, 207, 213, 0.28);
                border-radius: 12px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            #ProgressLabel {{
                color: {Palette.TEXT};
                font-size: 14px;
                font-weight: 600;
            }}
            QProgressBar {{
                background: {Palette.PANEL_ALT};
                border: 1px solid {Palette.BORDER};
                border-radius: 6px;
            }}
            QProgressBar::chunk {{
                border-radius: 6px;
                background: {Palette.CYAN};
            }}
            QPlainTextEdit {{
                background: #08101d;
                border: 1px solid {Palette.BORDER};
                border-radius: 18px;
                padding: 14px;
                color: #bafcff;
                selection-background-color: #20455a;
            }}
            #FooterCopy {{
                color: {Palette.MUTED};
                font-size: 12px;
            }}
            """
        )

    def log(self, text: str):
        self.log_box.appendPlainText(text)
        self.log_box.verticalScrollBar().setValue(
            self.log_box.verticalScrollBar().maximum()
        )

    def set_status(self, text: str):
        self.progress_label.setText(text)
        self.status_chip.setText(text.replace("...", ""))

    def set_progress(self, value: int):
        self.progress_bar.setValue(max(0, min(100, value)))

    def selected_platform(self) -> str:
        if self.mobile_radio.isChecked():
            return "mobile"
        if self.web_radio.isChecked():
            return "web"
        return "windows"

    def _load_saved_project_dir(self) -> str:
        saved = self.settings.value("project_dir", "", str)
        if saved and Path(saved).exists():
            return saved
        return str(Path.cwd())

    def _save_project_dir(self):
        self.settings.setValue("project_dir", self.project_dir)

    def _refresh_project_label(self):
        self.project_label.setText(f"Project directory\n{self.project_dir}")

    def choose_project_dir(self):
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Flutter project folder",
            self.project_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return
        self.project_dir = str(Path(selected).resolve())
        self._refresh_project_label()
        self._save_project_dir()
        self.log(f"Project directory updated: {self.project_dir}")

    def start_workflow(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, APP_TITLE, "A workflow is already running.")
            return

        platform = self.selected_platform()
        build_mode = self.build_radio.isChecked()
        clear_database = self.clear_db_check.isChecked()

        self.log_box.clear()
        self.log(f"Project directory: {self.project_dir}")
        self.log(f"Mode: {'build' if build_mode else 'run'}")
        self.log(f"Platform: {platform}")
        self.log(f"Clear database: {'yes' if clear_database else 'no'}")
        self.log("-" * 72)

        self.open_build_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.set_status("Starting workflow...")
        self.set_progress(5)

        self.worker = CommandWorker(
            project_dir=self.project_dir,
            platform=platform,
            build_mode=build_mode,
            clear_database=clear_database,
        )
        self.worker.log_signal.connect(self.log)
        self.worker.status_signal.connect(self.set_status)
        self.worker.progress_signal.connect(self.set_progress)
        self.worker.finished_signal.connect(self.on_workflow_finished)
        self.worker.launch_ready_signal.connect(self.on_launch_ready)
        self.worker.start()

    def cancel_workflow(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.set_status("Cancelling...")
            return
        self.log("No active workflow to cancel.")
        self.set_status("Idle")

    def on_launch_ready(self):
        self.log("✅ Flutter launch command started.")

    def on_workflow_finished(self, success: bool, message: str):
        self.start_button.setEnabled(True)

        if success:
            if self.build_radio.isChecked():
                self.build_output_path = message
                self.open_build_button.setEnabled(True)
                self.set_status("Build complete ✅")
                self.log(f"✅ Build output: {message}")
            else:
                self.set_status("App started 🚀")
                self.log("✅ Flutter app started.")
            self.set_progress(100)
        else:
            if message == "Cancelled":
                self.set_status("Cancelled ❌")
                self.log("🛑 Workflow cancelled.")
            else:
                self.set_status("Failed ❌")
                self.log(f"❌ {message}")

    def open_build_folder(self):
        if not self.build_output_path:
            return
        path = Path(self.build_output_path)
        if not path.exists():
            QMessageBox.warning(self, APP_TITLE, f"Build folder not found:\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())
