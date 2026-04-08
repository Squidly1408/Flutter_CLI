import os
import sys
import signal
import shutil
import subprocess
import ctypes
from pathlib import Path

import requests

try:
    import qtawesome as qta
except ImportError:
    qta = None

from PySide6.QtCore import Qt, QThread, Signal, QSize, QPoint, QSettings, QEvent
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QSizeGrip,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl


APP_TITLE = "Flutter Dev Launcher"
WINDOW_W = 1180
WINDOW_H = 760
LEFT_PANEL_W = 360


def resource_path(*parts: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base_path.joinpath(*parts)


APP_ICON_PATH = resource_path("assets", "logo.svg")


def set_windows_app_id(app_id: str):
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def extract_description_text(description):
    if description is None:
        return "No description."

    if isinstance(description, str):
        return description.strip() or "No description."

    if not isinstance(description, dict):
        return str(description)

    parts = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(description)
    text = "".join(parts).strip()
    return text if text else "No description."


def extract_ticket_comments(fields):
    comments = fields.get("comment", {}).get("comments", [])
    if not comments:
        return "No comments."

    blocks = []
    for comment in comments:
        author = comment.get("author", {}).get("displayName", "Unknown")
        body = extract_description_text(comment.get("body"))
        blocks.append(f"- {author}:\n{body}")
    return "\n\n".join(blocks)


def parse_project_keys(raw_keys: str):
    return [key.strip() for key in raw_keys.split(",") if key.strip()]


def extract_media_attachments(fields):
    attachments = fields.get("attachment", [])
    media = []
    for attachment in attachments:
        filename = attachment.get("filename", "unnamed")
        mime_type = (attachment.get("mimeType") or "").lower()
        lower_name = filename.lower()
        is_image = mime_type.startswith("image/") or lower_name.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")
        )
        is_video = mime_type.startswith("video/") or lower_name.endswith(
            (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")
        )

        if is_image or is_video:
            media.append(
                {
                    "filename": filename,
                    "mime": mime_type,
                    "kind": "image" if is_image else "video",
                    "url": attachment.get("content") or "",
                    "thumbnail": attachment.get("thumbnail") or "",
                }
            )
    return media


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.auth = (email, api_token)
        self.headers = {"Accept": "application/json"}

    def get_testing_tickets(self, board_digits: str):
        url = f"{self.base_url}/rest/api/3/search/jql"
        project_keys = parse_project_keys(board_digits)
        if not project_keys:
            raise ValueError("At least one Jira project key is required.")

        if len(project_keys) == 1:
            project_filter = f'project = "{project_keys[0]}"'
        else:
            joined = ", ".join([f'"{key}"' for key in project_keys])
            project_filter = f"project in ({joined})"

        jql = f'{project_filter} AND status = "Testing" ORDER BY updated DESC'
        params = {
            "jql": jql,
            "maxResults": 50,
            "fields": [
                "summary",
                "description",
                "status",
                "assignee",
                "priority",
                "comment",
                "attachment",
            ],
        }

        response = requests.get(
            url,
            auth=self.auth,
            headers=self.headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("issues", [])

    def fetch_binary(self, url: str):
        response = requests.get(
            url,
            auth=self.auth,
            headers={"Accept": "*/*"},
            timeout=30,
        )
        response.raise_for_status()
        return response.content


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


class JiraSettingsDialog(QDialog):
    def __init__(
        self,
        jira_url: str,
        jira_email: str,
        jira_api_token: str,
        jira_board_digits: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Jira Settings")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Jira URL"))
        self.jira_url_input = QLineEdit(jira_url)
        self.jira_url_input.setPlaceholderText("https://company.atlassian.net")
        layout.addWidget(self.jira_url_input)

        layout.addWidget(QLabel("Jira Email"))
        self.jira_email_input = QLineEdit(jira_email)
        self.jira_email_input.setPlaceholderText("you@company.com")
        layout.addWidget(self.jira_email_input)

        layout.addWidget(QLabel("Jira API Token"))
        self.jira_api_token_input = QLineEdit(jira_api_token)
        self.jira_api_token_input.setEchoMode(QLineEdit.Password)
        self.jira_api_token_input.setPlaceholderText("API token")
        layout.addWidget(self.jira_api_token_input)

        layout.addWidget(QLabel("Project Keys (comma-separated)"))
        self.jira_board_digits_input = QLineEdit(jira_board_digits)
        self.jira_board_digits_input.setPlaceholderText("IKD, CORE, MOBILE")
        layout.addWidget(self.jira_board_digits_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return (
            self.jira_url_input.text().strip(),
            self.jira_email_input.text().strip(),
            self.jira_api_token_input.text().strip(),
            self.jira_board_digits_input.text().strip(),
        )


class BranchSelectorDialog(QDialog):
    def __init__(self, branches: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Branch")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.all_branches = branches
        self.selected_branch = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Search box
        search_label = QLabel("Search branches:")
        layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type to filter branches...")
        self.search_input.textChanged.connect(self._filter_branches)
        layout.addWidget(self.search_input)

        # Branch list
        self.branch_list = QListWidget()
        self.branch_list.itemDoubleClicked.connect(self._on_branch_double_clicked)
        self._populate_branches()
        layout.addWidget(self.branch_list)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_branches(self):
        self.branch_list.clear()
        for branch in self.all_branches:
            self.branch_list.addItem(branch)

    def _filter_branches(self):
        search_text = self.search_input.text().lower()
        self.branch_list.clear()

        for branch in self.all_branches:
            if search_text in branch.lower():
                self.branch_list.addItem(branch)

    def _on_branch_double_clicked(self):
        self.accept()

    def get_selected_branch(self):
        current_item = self.branch_list.currentItem()
        if current_item:
            return current_item.text()
        return None


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
            self.log_signal.emit(">> Launching Flutter app...")
            ok = self._launch_flutter_run()
            if self._cancelled:
                self.finished_signal.emit(False, "Cancelled")
                return
            if not ok:
                self.finished_signal.emit(False, "Flutter launch failed.")
                return
            self.finished_signal.emit(True, "App closed")

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

    def _launch_flutter_run(self):
        if not self._flutter_cmd:
            self.log_signal.emit("⚠ Flutter executable is not available.")
            return False

        if self.platform == "windows":
            command = [self._flutter_cmd, "run", "-d", "windows"]
        elif self.platform == "mobile":
            command = [self._flutter_cmd, "run"]
        else:
            command = [self._flutter_cmd, "run", "-d", "chrome"]

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            self._launched_process = subprocess.Popen(
                command,
                cwd=self.project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=creationflags,
            )

            self.launch_ready_signal.emit()
            self.progress_signal.emit(100)

            assert self._launched_process.stdout is not None
            for line in self._launched_process.stdout:
                if self._cancelled:
                    self._kill_launched_process_tree()
                    return False
                self.log_signal.emit(line.rstrip())

            code = self._launched_process.wait()
            self._launched_process = None
            return code == 0
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
        self.drag_pos = None
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

        self.settings_btn = QPushButton("")
        self.min_btn = QPushButton("—")
        self.max_btn = QPushButton("□")
        self.close_btn = QPushButton("✕")
        self.settings_btn.setObjectName("TitleButton")
        self.min_btn.setObjectName("TitleButton")
        self.max_btn.setObjectName("TitleButton")
        self.close_btn.setObjectName("TitleButtonClose")
        self.settings_btn.setFixedSize(38, 34)
        self.min_btn.setFixedSize(38, 34)
        self.max_btn.setFixedSize(38, 34)
        self.close_btn.setFixedSize(38, 34)

        if qta is not None:
            self.settings_btn.setIcon(qta.icon("fa5s.cog", color=Palette.TEXT))
            self.settings_btn.setIconSize(QSize(15, 15))
        else:
            self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip("Jira Settings")

        self.settings_btn.clicked.connect(self._open_settings)
        self.min_btn.clicked.connect(self._minimize)
        self.max_btn.clicked.connect(self._toggle_maximize)
        self.close_btn.clicked.connect(self._close)

        layout.addWidget(self.settings_btn)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def _open_settings(self):
        if self.parent_window:
            self.parent_window.open_jira_settings_dialog()

    def _minimize(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def _close(self):
        if self.parent_window:
            self.parent_window.close()

    def _toggle_maximize(self):
        if not self.parent_window:
            return

        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
            self.max_btn.setText("□")
        else:
            self.parent_window.showMaximized()
            self.max_btn.setText("❐")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.parent_window:
            handle = self.parent_window.windowHandle()
            if handle and handle.startSystemMove():
                self.drag_pos = None
                event.accept()
                return

            self.drag_pos = (
                event.globalPosition().toPoint()
                - self.parent_window.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.drag_pos is not None:
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.dragging = False
        self.settings = QSettings("FlutterDevLauncher", "Launcher")
        self.jira_url = self.settings.value(
            "jira_url", "https://saphi.atlassian.net", str
        )
        self.jira_email = self.settings.value("jira_email", "", str)
        self.jira_api_token = self.settings.value("jira_api_token", "", str)
        self.jira_board_digits = self.settings.value("jira_board_digits", "IKD", str)
        self.testing_tickets = []
        self.current_ticket_media = []
        self.selected_ticket_key = ""
        self.project_dir = self._load_saved_project_dir()
        self.build_output_path = None

        self.setWindowTitle(APP_TITLE)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setMinimumSize(QSize(WINDOW_W, WINDOW_H))
        self.resize(WINDOW_W, WINDOW_H)
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QWidget()
        self.outer_layout = QVBoxLayout(outer)
        self.outer_layout.setContentsMargins(18, 18, 18, 18)

        self.shell = QFrame()
        self.shell.setObjectName("Shell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.titlebar = TitleBar(self)
        shell_layout.addWidget(self.titlebar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 18, 18, 18)
        body_layout.setSpacing(18)

        shell_layout.addWidget(body)
        self.outer_layout.addWidget(self.shell)
        self.setCentralWidget(outer)

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        body_layout.addWidget(left_panel, 0)
        body_layout.addWidget(right_panel, 1)

        resize_row = QHBoxLayout()
        resize_row.setContentsMargins(0, 0, 10, 10)
        resize_row.setSpacing(0)
        resize_row.addStretch()
        self.size_grip = QSizeGrip(self.shell)
        self.size_grip.setToolTip("Drag to resize")
        resize_row.addWidget(self.size_grip, 0, Qt.AlignRight | Qt.AlignBottom)
        shell_layout.addLayout(resize_row)

        self._apply_styles()
        self._update_window_chrome()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._update_window_chrome()

    def _update_window_chrome(self):
        maximized = self.isMaximized()
        margin = 0 if maximized else 18
        self.outer_layout.setContentsMargins(margin, margin, margin, margin)
        self.shell.setProperty("maximized", maximized)
        self.titlebar.setProperty("maximized", maximized)
        self.size_grip.setVisible(not maximized)
        self.titlebar.max_btn.setText("❐" if maximized else "□")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

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

        self.view_testing_tickets_button = QPushButton("View Testing Tickets")
        self.view_testing_tickets_button.setObjectName("GhostButton")
        self.view_testing_tickets_button.clicked.connect(self.open_testing_tickets)
        layout.addWidget(self.view_testing_tickets_button)

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
        scroll = QScrollArea()
        scroll.setObjectName("RightPanelScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

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
        self.log_box.setMinimumHeight(130)
        self.log_box.setMaximumHeight(180)
        font = QFont("Consolas")
        font.setPointSize(10)
        self.log_box.setFont(font)
        layout.addWidget(self.log_box)

        tickets_header = QHBoxLayout()
        tickets_header.setSpacing(10)

        tickets_title = QLabel("Testing Tickets")
        tickets_title.setObjectName("SectionTitle")

        self.checkout_ticket_branch_button = QPushButton("Checkout Ticket Branch")
        self.checkout_ticket_branch_button.setObjectName("SecondaryButton")
        self.checkout_ticket_branch_button.setEnabled(False)
        self.checkout_ticket_branch_button.clicked.connect(self.checkout_ticket_branch)

        self.checkout_dev_branch_button = QPushButton("Checkout Dev")
        self.checkout_dev_branch_button.setObjectName("GhostButton")
        self.checkout_dev_branch_button.clicked.connect(self.checkout_dev_branch)

        self.fetch_branch_changes_button = QPushButton("Fetch Branch Changes")
        self.fetch_branch_changes_button.setObjectName("GhostButton")
        self.fetch_branch_changes_button.clicked.connect(
            self.fetch_current_branch_changes
        )

        self.open_vscode_button = QPushButton("Open VS Code")
        self.open_vscode_button.setObjectName("GhostButton")
        self.open_vscode_button.clicked.connect(self.open_vscode)
        if qta is not None:
            self.open_vscode_button.setIcon(
                qta.icon("mdi.code-braces", color=Palette.TEXT)
            )
            self.open_vscode_button.setIconSize(QSize(15, 15))

        self.open_github_desktop_button = QPushButton("Open GitHub Desktop")
        self.open_github_desktop_button.setObjectName("GhostButton")
        self.open_github_desktop_button.clicked.connect(self.open_github_desktop)
        if qta is not None:
            self.open_github_desktop_button.setIcon(
                qta.icon("fa5s.code-branch", color=Palette.TEXT)
            )
            self.open_github_desktop_button.setIconSize(QSize(15, 15))

        self.select_branch_button = QPushButton("Select Branch")
        self.select_branch_button.setObjectName("GhostButton")
        self.select_branch_button.clicked.connect(self.select_and_checkout_branch)
        if qta is not None:
            self.select_branch_button.setIcon(
                qta.icon("fa5s.code-branch", color=Palette.TEXT)
            )
            self.select_branch_button.setIconSize(QSize(15, 15))

        self.git_pull_from_dev_button = QPushButton("Pull from Dev")
        self.git_pull_from_dev_button.setObjectName("GhostButton")
        self.git_pull_from_dev_button.clicked.connect(self.git_pull_from_dev)
        if qta is not None:
            self.git_pull_from_dev_button.setIcon(
                qta.icon("fa5s.download", color=Palette.TEXT)
            )
            self.git_pull_from_dev_button.setIconSize(QSize(15, 15))

        tickets_header.addWidget(tickets_title)
        tickets_header.addStretch()
        tickets_header.addWidget(self.fetch_branch_changes_button)
        tickets_header.addWidget(self.checkout_dev_branch_button)
        tickets_header.addWidget(self.checkout_ticket_branch_button)
        layout.addLayout(tickets_header)

        # Add a second row of buttons for VSCode, GitHub Desktop, Branch Selector, and Pull from Dev
        tools_header = QHBoxLayout()
        tools_header.setSpacing(10)
        tools_header.addStretch()
        tools_header.addWidget(self.git_pull_from_dev_button)
        tools_header.addWidget(self.select_branch_button)
        tools_header.addWidget(self.open_vscode_button)
        tools_header.addWidget(self.open_github_desktop_button)
        layout.addLayout(tools_header)

        self.ticket_scope_label = QLabel("Projects: not loaded")
        self.ticket_scope_label.setObjectName("FooterCopy")
        layout.addWidget(self.ticket_scope_label)

        self.testing_ticket_list = QListWidget()
        self.testing_ticket_list.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.testing_ticket_list.itemClicked.connect(self.show_testing_ticket_details)

        self.testing_ticket_details = QTextEdit()
        self.testing_ticket_details.setReadOnly(True)
        self.testing_ticket_details.setPlaceholderText(
            "Use 'View Testing Tickets' to load and select a ticket."
        )
        self.testing_ticket_details.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

        tickets_splitter = QSplitter(Qt.Horizontal)
        tickets_splitter.addWidget(self.testing_ticket_list)
        tickets_splitter.addWidget(self.testing_ticket_details)
        tickets_splitter.setStretchFactor(0, 2)
        tickets_splitter.setStretchFactor(1, 3)
        tickets_splitter.setChildrenCollapsible(False)
        tickets_splitter.setMinimumHeight(250)
        tickets_splitter.setSizes([280, 520])
        layout.addWidget(tickets_splitter, 1)

        media_title = QLabel("Images / Videos")
        media_title.setObjectName("SectionTitle")
        layout.addWidget(media_title)

        self.ticket_media_list = QListWidget()
        self.ticket_media_list.setMaximumHeight(150)
        self.ticket_media_list.itemClicked.connect(self.preview_ticket_media)
        self.ticket_media_list.itemDoubleClicked.connect(self.open_ticket_media)

        self.image_preview = QLabel(
            "Select media to preview. Double-click to open in browser."
        )
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setWordWrap(True)
        self.image_preview.setMinimumHeight(150)
        self.image_preview.setObjectName("PathCard")

        media_splitter = QSplitter(Qt.Horizontal)
        media_splitter.addWidget(self.ticket_media_list)
        media_splitter.addWidget(self.image_preview)
        media_splitter.setStretchFactor(0, 2)
        media_splitter.setStretchFactor(1, 3)
        media_splitter.setChildrenCollapsible(False)
        media_splitter.setSizes([280, 520])
        layout.addWidget(media_splitter)

        footer = QLabel(
            "Made for local Flutter desktop automation • clean • run • generate • build"
        )
        footer.setObjectName("FooterCopy")
        layout.addWidget(footer)

        scroll.setWidget(panel)
        return scroll

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
            #Shell[maximized="true"] {{
                border-radius: 0px;
                border: none;
            }}
            #TitleBar {{
                background: rgba(255,255,255,0.02);
                border-top-left-radius: 26px;
                border-top-right-radius: 26px;
                border-bottom: 1px solid {Palette.BORDER};
            }}
            #TitleBar[maximized="true"] {{
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
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
            #RightPanelScroll {{
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
            QTextEdit {{
                background: #08101d;
                border: 1px solid {Palette.BORDER};
                border-radius: 18px;
                padding: 12px;
                color: #d9f6ff;
                selection-background-color: #20455a;
            }}
            QListWidget {{
                background: #08101d;
                border: 1px solid {Palette.BORDER};
                border-radius: 16px;
                padding: 8px;
            }}
            QSplitter::handle {{
                background: rgba(148, 167, 198, 0.20);
                border-radius: 2px;
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
                self.set_status("App closed ✅")
                self.log("✅ Flutter app exited.")
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

    def save_jira_settings(
        self,
        jira_url: str,
        jira_email: str,
        jira_api_token: str,
        jira_board_digits: str,
        show_success_message: bool = True,
    ) -> bool:
        if (
            not jira_url
            or not jira_email
            or not jira_api_token
            or not jira_board_digits
        ):
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Please fill in Jira URL, email, API token, and board digits/project key.",
            )
            return False

        self.jira_url = jira_url
        self.jira_email = jira_email
        self.jira_api_token = jira_api_token
        self.jira_board_digits = jira_board_digits

        self.settings.setValue("jira_url", self.jira_url)
        self.settings.setValue("jira_email", self.jira_email)
        self.settings.setValue("jira_api_token", self.jira_api_token)
        self.settings.setValue("jira_board_digits", self.jira_board_digits)
        self.log("Jira settings saved.")
        if show_success_message:
            QMessageBox.information(self, APP_TITLE, "Jira settings saved.")
        return True

    def has_jira_settings(self) -> bool:
        return all(
            [
                self.jira_url.strip(),
                self.jira_email.strip(),
                self.jira_api_token.strip(),
                self.jira_board_digits.strip(),
            ]
        )

    def open_jira_settings_dialog(self):
        dialog = JiraSettingsDialog(
            jira_url=self.jira_url,
            jira_email=self.jira_email,
            jira_api_token=self.jira_api_token,
            jira_board_digits=self.jira_board_digits,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        jira_url, jira_email, jira_api_token, jira_board_digits = dialog.get_values()
        self.save_jira_settings(
            jira_url=jira_url,
            jira_email=jira_email,
            jira_api_token=jira_api_token,
            jira_board_digits=jira_board_digits,
            show_success_message=True,
        )

    def open_testing_tickets(self):
        if not self.has_jira_settings():
            QMessageBox.information(
                self,
                APP_TITLE,
                "Open settings in the top-right gear button and save Jira credentials first.",
            )
            return

        self.load_testing_tickets()

    def load_testing_tickets(self):
        self.testing_ticket_list.clear()
        self.ticket_media_list.clear()
        self.selected_ticket_key = ""
        self.checkout_ticket_branch_button.setEnabled(False)
        self.testing_ticket_details.setPlainText("Loading testing tickets...")
        self.image_preview.setText(
            "Select media to preview. Double-click to open in browser."
        )
        self.ticket_scope_label.setText(
            f"Projects: {', '.join(parse_project_keys(self.jira_board_digits)) or 'not set'}"
        )

        try:
            client = JiraClient(self.jira_url, self.jira_email, self.jira_api_token)
            self.testing_tickets = client.get_testing_tickets(self.jira_board_digits)

            if not self.testing_tickets:
                self.testing_ticket_details.setPlainText(
                    "No testing tickets found for the current board digits/project key."
                )
                self.log("No testing tickets found.")
                return

            for ticket in self.testing_tickets:
                key = ticket.get("key", "UNKNOWN")
                summary = ticket.get("fields", {}).get("summary", "No summary")
                self.testing_ticket_list.addItem(QListWidgetItem(f"{key} - {summary}"))

            self.testing_ticket_details.setPlainText(
                f"Loaded {len(self.testing_tickets)} testing ticket(s). Select one to view details."
            )
            self.log(f"Loaded {len(self.testing_tickets)} testing tickets from Jira.")

        except ValueError as exc:
            self.testing_ticket_details.setPlainText(str(exc))
            self.log(str(exc))
            QMessageBox.warning(self, APP_TITLE, str(exc))
        except requests.exceptions.RequestException as exc:
            self.testing_ticket_details.setPlainText(
                f"Failed to load Jira tickets:\n{exc}"
            )
            self.log(f"Failed to load Jira tickets: {exc}")
            QMessageBox.critical(
                self, "Jira Error", f"Failed to load Jira tickets:\n{exc}"
            )

    def show_testing_ticket_details(self, item):
        index = self.testing_ticket_list.row(item)
        if index < 0 or index >= len(self.testing_tickets):
            return

        ticket = self.testing_tickets[index]
        self.selected_ticket_key = ticket.get("key", "").strip()
        self.checkout_ticket_branch_button.setEnabled(bool(self.selected_ticket_key))
        fields = ticket.get("fields", {})

        assignee = fields.get("assignee")
        assignee_name = (
            assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
        )

        status = fields.get("status", {})
        status_name = (
            status.get("name", "N/A") if isinstance(status, dict) else str(status)
        )

        priority = fields.get("priority")
        priority_name = (
            priority.get("name", "N/A") if isinstance(priority, dict) else "N/A"
        )

        summary = fields.get("summary", "N/A")
        description = extract_description_text(fields.get("description"))
        comments = extract_ticket_comments(fields)
        media = extract_media_attachments(fields)
        self.current_ticket_media = media

        self.ticket_media_list.clear()
        self.image_preview.setText(
            "Select media to preview. Double-click to open in browser."
        )
        if not media:
            self.ticket_media_list.addItem(QListWidgetItem("No images/videos attached"))
        else:
            for media_item in media:
                prefix = "[Image]" if media_item.get("kind") == "image" else "[Video]"
                item = QListWidgetItem(f"{prefix} {media_item['filename']}")
                item.setData(Qt.UserRole, media_item)
                self.ticket_media_list.addItem(item)

        media_lines = []
        for media_item in media:
            media_kind = "Image" if media_item.get("kind") == "image" else "Video"
            media_url = media_item.get("url") or "No URL available"
            media_lines.append(
                f"- {media_kind}: {media_item['filename']}\n  {media_url}"
            )
        media_text = (
            "\n\n".join(media_lines) if media_lines else "No images/videos attached"
        )

        details_text = (
            f"KEY:\n{ticket.get('key', 'N/A')}\n\n"
            f"SUMMARY:\n{summary}\n\n"
            f"STATUS:\n{status_name}\n\n"
            f"ASSIGNEE:\n{assignee_name}\n\n"
            f"PRIORITY:\n{priority_name}\n\n"
            f"DESCRIPTION:\n{description}\n\n"
            f"COMMENTS:\n{comments}\n\n"
            f"MEDIA FILES ({len(media)}):\n{media_text}"
        )
        self.testing_ticket_details.setPlainText(details_text)

    def _run_git_command(self, args):
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        completed = subprocess.run(
            ["git", *args],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
            creationflags=creationflags,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode == 0, output.strip()

    def _is_git_repository(self):
        ok, output = self._run_git_command(["rev-parse", "--is-inside-work-tree"])
        return ok and output.lower().endswith("true")

    def _find_branch_by_ticket_tag(self, ticket_key: str):
        matches = self._find_branches_by_ticket_tag(ticket_key)
        if not matches:
            return (None, None)
        scope, branch = matches[0]
        return (scope, branch)

    def _get_local_branches(self):
        ok_local, local_output = self._run_git_command(["branch", "--list"])
        if not ok_local:
            return []

        branches = []
        for line in local_output.splitlines():
            branch = line.strip().lstrip("* ").strip()
            if branch:
                branches.append(branch)
        return branches

    def _get_remote_branches(self):
        ok_remote, remote_output = self._run_git_command(["branch", "-r", "--list"])
        if not ok_remote:
            return []

        branches = []
        for line in remote_output.splitlines():
            branch = line.strip()
            if not branch or "->" in branch:
                continue
            branches.append(branch)
        return branches

    def _find_branches_by_ticket_tag(self, ticket_key: str):
        key_lower = ticket_key.lower()
        matches = []

        for branch in self._get_local_branches():
            if key_lower in branch.lower():
                matches.append(("local", branch))

        for branch in self._get_remote_branches():
            if key_lower in branch.lower():
                matches.append(("remote", branch))

        return matches

    def _collect_ticket_branch_matches(self, ticket_key: str, candidates):
        matches = []
        seen = set()

        local_branches = self._get_local_branches()
        remote_branches = self._get_remote_branches()

        for branch in candidates:
            if branch in local_branches and ("local", branch) not in seen:
                seen.add(("local", branch))
                matches.append(("local", branch))

            remote_name = f"origin/{branch}"
            if remote_name in remote_branches and ("remote", remote_name) not in seen:
                seen.add(("remote", remote_name))
                matches.append(("remote", remote_name))

        ticket_matches = self._find_branches_by_ticket_tag(ticket_key)
        for scope, branch in ticket_matches:
            if (scope, branch) not in seen:
                seen.add((scope, branch))
                matches.append((scope, branch))

        return matches

    def _choose_branch_match(self, matches, ticket_key: str):
        if len(matches) == 1:
            return matches[0]

        options = [f"{scope}: {branch}" for scope, branch in matches]
        choice, ok = QInputDialog.getItem(
            self,
            APP_TITLE,
            f"Multiple branches found for {ticket_key}. Choose one:",
            options,
            0,
            False,
        )
        if not ok or not choice:
            return (None, None)

        selected_index = options.index(choice)
        return matches[selected_index]

    def _checkout_branch_reference(self, scope: str, branch: str):
        if scope == "local":
            ok, output = self._run_git_command(["checkout", branch])
            return ok, branch, output

        ok, output = self._run_git_command(["checkout", "-t", branch])
        if ok:
            local_name = branch.split("/", 1)[1] if "/" in branch else branch
            return True, local_name, output

        local_name = branch.split("/", 1)[1] if "/" in branch else branch
        ok, output = self._run_git_command(["checkout", local_name])
        if ok:
            return True, local_name, output

        return False, branch, output

    def _resolve_dev_branch_ref(self):
        local_branches = self._get_local_branches()
        if "dev" in local_branches:
            return "dev"

        remote_branches = self._get_remote_branches()
        if "origin/dev" in remote_branches:
            return "origin/dev"

        return None

    def _get_current_branch(self):
        ok, output = self._run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
        if not ok:
            return None

        branch = output.splitlines()[-1].strip() if output else ""
        if not branch or branch == "HEAD":
            return None
        return branch

    def _get_upstream_branch(self, branch_name: str):
        ok, output = self._run_git_command(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
        )
        if ok and output:
            return output.splitlines()[-1].strip()

        fallback = f"origin/{branch_name}"
        if fallback in self._get_remote_branches():
            return fallback
        return None

    def fetch_current_branch_changes(self):
        if not self._is_git_repository():
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"The selected project folder is not a git repository:\n{self.project_dir}",
            )
            return

        current_branch = self._get_current_branch()
        if not current_branch:
            QMessageBox.information(
                self,
                APP_TITLE,
                "The current checkout is detached. Switch to a branch before fetching branch changes.",
            )
            return

        upstream_branch = self._get_upstream_branch(current_branch)
        if not upstream_branch:
            QMessageBox.information(
                self,
                APP_TITLE,
                f"No upstream branch is configured for {current_branch}.",
            )
            return

        remote_name, remote_branch = upstream_branch.split("/", 1)
        self.log(f"Fetching updates for {current_branch} from {upstream_branch}...")

        ok, output = self._run_git_command(
            ["fetch", remote_name, remote_branch, "--prune"]
        )
        if not ok:
            self.log(f"Unable to fetch {upstream_branch}. {output}")
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"Could not fetch updates for {upstream_branch}.\n\n{output or 'Unknown git error.'}",
            )
            return

        count_ok, count_output = self._run_git_command(
            ["rev-list", "--count", f"{current_branch}..{upstream_branch}"]
        )
        behind_count = (
            int(count_output.strip())
            if count_ok and count_output.strip().isdigit()
            else 0
        )

        log_ok, log_output = self._run_git_command(
            [
                "log",
                "--oneline",
                "--decorate",
                "-n",
                "10",
                f"{current_branch}..{upstream_branch}",
            ]
        )
        recent_commits = log_output.strip() if log_ok else ""

        if behind_count == 0:
            self.log(f"{current_branch} is up to date with {upstream_branch}.")
            QMessageBox.information(
                self,
                APP_TITLE,
                f"Fetched {upstream_branch}.\n\n{current_branch} is already up to date.",
            )
            return

        self.log(
            f"Fetched {upstream_branch}. {current_branch} is behind by {behind_count} commit(s)."
        )
        if recent_commits:
            self.log("Recent remote commits:")
            self.log(recent_commits)

        summary = (
            f"Fetched {upstream_branch}.\n\n"
            f"{current_branch} is behind by {behind_count} commit(s)."
        )
        if recent_commits:
            summary = f"{summary}\n\nRecent remote commits:\n{recent_commits}"

        QMessageBox.information(self, APP_TITLE, summary)

    def _is_branch_merged_into_dev(self, branch_name: str):
        dev_ref = self._resolve_dev_branch_ref()
        if not dev_ref:
            return False

        ok, _ = self._run_git_command(
            ["merge-base", "--is-ancestor", branch_name, dev_ref]
        )
        return ok

    def _prompt_dev_checkout_if_merged(self, branch_name: str):
        if not self._is_branch_merged_into_dev(branch_name):
            return

        response = QMessageBox.question(
            self,
            APP_TITLE,
            (
                f"{branch_name} appears to be merged into dev.\n\n"
                "Do you want to switch to dev for testing?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if response == QMessageBox.Yes:
            self.checkout_dev_branch()

    def checkout_dev_branch(self):
        if not self._is_git_repository():
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"The selected project folder is not a git repository:\n{self.project_dir}",
            )
            return

        self.log("Checking out dev branch...")
        self._run_git_command(["fetch", "--all", "--prune"])

        ok, output = self._run_git_command(["checkout", "dev"])
        if ok:
            self.log("Checked out branch: dev")
            QMessageBox.information(self, APP_TITLE, "Checked out branch:\ndev")
            return

        ok, output = self._run_git_command(["checkout", "-t", "origin/dev"])
        if ok:
            self.log("Checked out branch: dev (tracking origin/dev)")
            QMessageBox.information(self, APP_TITLE, "Checked out branch:\ndev")
            return

        self.log(f"Unable to checkout dev branch. {output}")
        QMessageBox.warning(
            self,
            APP_TITLE,
            "Could not checkout dev branch. Ensure 'dev' or 'origin/dev' exists.",
        )

    def checkout_ticket_branch(self):
        if not self.selected_ticket_key:
            QMessageBox.information(self, APP_TITLE, "Select a testing ticket first.")
            return

        if not self._is_git_repository():
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"The selected project folder is not a git repository:\n{self.project_dir}",
            )
            return

        ticket_key = self.selected_ticket_key
        candidates = [
            ticket_key,
            ticket_key.lower(),
            f"feature/{ticket_key}",
            f"feature/{ticket_key.lower()}",
            f"bugfix/{ticket_key}",
            f"bugfix/{ticket_key.lower()}",
        ]

        self.log(f"Checking out branch for ticket {ticket_key}...")
        self._run_git_command(["fetch", "--all", "--prune"])

        matches = self._collect_ticket_branch_matches(ticket_key, candidates)
        if matches:
            scope, matched_branch = self._choose_branch_match(matches, ticket_key)
            if not scope or not matched_branch:
                self.log("Branch selection cancelled.")
                return

            ok, checked_out_branch, output = self._checkout_branch_reference(
                scope, matched_branch
            )
            if ok:
                self.log(f"Checked out {scope} branch by ticket tag: {matched_branch}")
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    f"Checked out branch by ticket tag:\n{checked_out_branch}",
                )
                self._prompt_dev_checkout_if_merged(checked_out_branch)
                return

        self.log(f"No existing branch found for ticket {ticket_key}.")
        QMessageBox.warning(
            self,
            APP_TITLE,
            f"No existing branch found for ticket {ticket_key}.\n\n"
            "Searched exact names and branches containing the ticket tag.",
        )

    def open_vscode(self):
        """Open VS Code with the project directory."""
        if not self.project_dir:
            QMessageBox.warning(
                self,
                APP_TITLE,
                "No project directory selected.",
            )
            return

        try:
            if os.name == "nt":
                # On Windows, 'code' is a .cmd script that requires cmd.exe to run.
                subprocess.Popen(
                    ["cmd", "/c", "code", self.project_dir],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                subprocess.Popen(["code", self.project_dir])
            self.log(f"Opening VS Code: {self.project_dir}")
        except FileNotFoundError:
            # Fallback: try the common install location
            vscode_exe = (
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Programs"
                / "Microsoft VS Code"
                / "Code.exe"
            )
            if vscode_exe.exists():
                try:
                    subprocess.Popen(
                        [str(vscode_exe), self.project_dir],
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        ),
                    )
                    self.log(f"Opening VS Code: {self.project_dir}")
                    return
                except Exception as exc2:
                    QMessageBox.warning(
                        self, APP_TITLE, f"Failed to open VS Code: {exc2}"
                    )
                    return
            QMessageBox.warning(
                self,
                APP_TITLE,
                "VS Code is not installed or not found in system PATH. "
                "Please install VS Code or add it to your PATH.",
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"Failed to open VS Code: {exc}",
            )

    def open_github_desktop(self):
        """Open GitHub Desktop with the project directory."""
        if not self.project_dir:
            QMessageBox.warning(
                self,
                APP_TITLE,
                "No project directory selected.",
            )
            return

        launched = False

        if os.name == "nt":
            # GitHub Desktop on Windows lives under %LOCALAPPDATA%\GitHubDesktop\
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            github_desktop_exe = (
                Path(local_app_data) / "GitHubDesktop" / "GitHubDesktop.exe"
            )
            if github_desktop_exe.exists():
                try:
                    subprocess.Popen(
                        [str(github_desktop_exe), self.project_dir],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    self.log(f"Opening GitHub Desktop: {self.project_dir}")
                    launched = True
                except Exception as exc:
                    self.log(f"⚠ Failed to launch GitHub Desktop exe: {exc}")

        if not launched:
            # Fallback: open the project folder in Explorer so the user can drag it in
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.project_dir))))
            QMessageBox.information(
                self,
                APP_TITLE,
                "GitHub Desktop executable not found.\n\n"
                "The project folder has been opened in Explorer instead. "
                "Drag it into GitHub Desktop to open the repository.",
            )

    def git_pull_from_dev(self):
        """Pull the latest changes from origin/dev into the current branch."""
        if not self._is_git_repository():
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"The selected project folder is not a git repository:\n{self.project_dir}",
            )
            return

        current_branch = self._get_current_branch()
        if not current_branch:
            QMessageBox.information(
                self,
                APP_TITLE,
                "The current checkout is detached. Switch to a branch before pulling.",
            )
            return

        self.log("Fetching dev from origin...")
        ok_fetch, fetch_output = self._run_git_command(
            ["fetch", "origin", "dev", "--prune"]
        )
        if not ok_fetch:
            self.log(f"Unable to fetch origin/dev. {fetch_output}")
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"Could not fetch origin/dev.\n\n{fetch_output or 'Unknown git error.'}",
            )
            return

        self.log(f"Pulling origin/dev into {current_branch}...")
        ok_pull, pull_output = self._run_git_command(["pull", "origin", "dev"])
        self.log(pull_output or "(no output)")

        if ok_pull:
            QMessageBox.information(
                self,
                APP_TITLE,
                f"Successfully pulled origin/dev into {current_branch}.\n\n"
                + (pull_output or ""),
            )
        else:
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"git pull origin dev failed.\n\n{pull_output or 'Unknown git error.'}",
            )

    def select_and_checkout_branch(self):
        """Open branch selector dialog and checkout selected branch."""
        if not self._is_git_repository():
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"The selected project folder is not a git repository:\n{self.project_dir}",
            )
            return

        self.log("Fetching branches...")
        self._run_git_command(["fetch", "--all", "--prune"])

        # Get all branches (local and remote)
        local_branches = self._get_local_branches()
        remote_branches = self._get_remote_branches()

        all_branches = []

        # Add local branches first
        for branch in local_branches:
            all_branches.append(f"[local] {branch}")

        # Add remote branches
        for branch in remote_branches:
            if not any(
                local.endswith(branch.split("/", 1)[1] if "/" in branch else branch)
                for local in local_branches
            ):
                all_branches.append(f"[remote] {branch}")

        if not all_branches:
            QMessageBox.information(
                self,
                APP_TITLE,
                "No branches found in the repository.",
            )
            return

        # Show branch selector dialog
        dialog = BranchSelectorDialog(all_branches, self)
        if dialog.exec() != QDialog.Accepted:
            self.log("Branch selection cancelled.")
            return

        selected = dialog.get_selected_branch()
        if not selected:
            return

        self.log(f"Checking out branch: {selected}")

        # Parse the branch name (remove the [local] or [remote] prefix)
        if selected.startswith("[local] "):
            branch_name = selected[8:]
            scope = "local"
        elif selected.startswith("[remote] "):
            branch_name = selected[9:]
            scope = "remote"
        else:
            branch_name = selected
            scope = "local"

        # Checkout the branch
        ok, checked_out_branch, output = self._checkout_branch_reference(
            scope, branch_name
        )
        if ok:
            self.log(f"Checked out branch: {checked_out_branch}")
            QMessageBox.information(
                self,
                APP_TITLE,
                f"Checked out branch:\n{checked_out_branch}",
            )
            self._prompt_dev_checkout_if_merged(checked_out_branch)
        else:
            self.log(f"Failed to checkout branch: {output}")
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"Failed to checkout branch:\n{output}",
            )

    def preview_ticket_media(self, item):
        media_item = item.data(Qt.UserRole)
        if not isinstance(media_item, dict):
            return

        url = media_item.get("url")
        mime = media_item.get("mime", "")
        if not url:
            self.image_preview.setText("No media URL available.")
            return

        if media_item.get("kind") == "video" or mime.startswith("video/"):
            self.image_preview.setText(
                f"Video selected:\n{media_item.get('filename', 'video')}\n\nDouble-click to open in browser."
            )
            return

        if media_item.get("kind") != "image" and not mime.startswith("image/"):
            self.image_preview.setText("Unsupported media format.")
            return

        try:
            client = JiraClient(self.jira_url, self.jira_email, self.jira_api_token)
            binary = client.fetch_binary(url)
            pixmap = QPixmap()
            if not pixmap.loadFromData(binary):
                self.image_preview.setText("Unable to render image preview.")
                return

            scaled = pixmap.scaled(
                self.image_preview.width() - 16,
                self.image_preview.height() - 16,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.image_preview.setPixmap(scaled)
        except requests.exceptions.RequestException as exc:
            self.image_preview.setText(f"Failed to load image preview:\n{exc}")

    def open_ticket_media(self, item):
        media_item = item.data(Qt.UserRole)
        if not isinstance(media_item, dict):
            return
        url = media_item.get("url")
        if url:
            QDesktopServices.openUrl(QUrl(url))


if __name__ == "__main__":
    set_windows_app_id("com.lucasnewman.flutterdevlauncher")
    app = QApplication(sys.argv)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())
