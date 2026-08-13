"""
gui/styles.py

Система тем для всего приложения: светлая, тёмная и «авто» (следует за
системной схемой macOS). Каждая тема — набор цветовых токенов, из которых
собираются QSS-стиль, QPalette и палитра иконок.

Используется MainWindow, LoginDialog, результатной таблицей и другими
виджетами. При смене темы все зарегистрированные слушатели вызываются
заново, чтобы переприменить стиль, палитру и иконки.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

# Цветовые токены светлой темы (Tailwind-подобная палитра slate/blue).
LIGHT = {
    "window": "#eef2f7",
    "card": "#ffffff",
    "card_border": "#cbd5e1",
    "border": "#cbd5e1",
    "border_strong": "#94a3b8",
    "divider": "#e2e8f0",
    "hover_bg": "#f1f5f9",
    "hover_bg_strong": "#eef2f7",
    "text": "#0f172a",
    "text_secondary": "#475569",
    "text_muted": "#64748b",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_active": "#1e40af",
    "accent_top": "#3b82f6",
    "accent_bottom": "#2563eb",
    "accent_soft": "#eff6ff",
    "accent_soft_active": "#dbeafe",
    "sel_bg": "#dbeafe",
    "sel_text": "#1e40af",
    "danger": "#dc2626",
    "danger_hover": "#b91c1c",
    "danger_active": "#991b1b",
    "danger_soft": "#fef2f2",
    "danger_soft_active": "#fee2e2",
    "success": "#16a34a",
    "warning": "#d97706",
    "error_bg": "#fff5f5",
    "header_bg": "#f1f5f9",
    "header_border": "#d7dfea",
    "header_text": "#334155",
    "header_hover": "#e2e8f0",
    "status_bg": "#ffffff",
    "status_border": "#d7dfea",
    "status_label": "#64748b",
    "status_value": "#334155",
    "status_progress_bg": "#cbd5e1",
    "input_bg": "#ffffff",
    "input_focus": "#2563eb",
    "editor_gutter_bg": "#f8fafc",
    "editor_gutter_border": "#e3e8ef",
    "editor_line_number": "#94a3b8",
    "editor_current_line": "#2563eb",
    "tooltip_bg": "#0f172a",
    "tooltip_text": "#f8fafc",
    "scrollbar": "#cbd5e1",
    "scrollbar_hover": "#94a3b8",
    "icon_fg": "#0f172a",
    "icon_muted": "#475569",
    "icon_accent": "#1d4ed8",
    "icon_secondary": "#6d28d9",
    "icon_success": "#15803d",
    "icon_danger": "#dc2626",
    # Фирменные цвета движков БД (официальные, на светлом фоне).
    "mysql_brand": "#3b6d99",
    "mssql_brand": "#b91c1c",
    "pgsql_brand": "#336791",
    "alt_base": "#f8fafc",
    "sql_keyword": "#1565c0",
    "sql_string": "#2e7d32",
    "sql_number": "#ef6c00",
    "sql_comment": "#7f8c8d",
    "sql_identifier": "#00838f",
    "log_info": "#2563eb",
    "log_success": "#16a34a",
    "log_warning": "#d97706",
    "log_error": "#dc2626",
    "log_stamp": "#94a3b8",
    "log_text": "#0f172a",
}

# Цветовые токены тёмной темы: чисто-чёрный фон, нейтральные серые,
# синий — только в акцентах и выделении.
DARK = {
    "window": "#000000",
    "card": "#121212",
    "card_border": "#2a2a2a",
    "border": "#232323",
    "border_strong": "#3d3d3d",
    "divider": "#1c1c1c",
    "hover_bg": "#1a1a1a",
    "hover_bg_strong": "#262626",
    "text": "#ffffff",
    "text_secondary": "#cfcfcf",
    "text_muted": "#8f8f8f",
    "accent": "#3b82f6",
    "accent_hover": "#60a5fa",
    "accent_active": "#2563eb",
    "accent_top": "#60a5fa",
    "accent_bottom": "#3b82f6",
    "accent_soft": "#16161a",
    "accent_soft_active": "#20242e",
    "sel_bg": "#1e3a8a",
    "sel_text": "#ffffff",
    "danger": "#f87171",
    "danger_hover": "#ef4444",
    "danger_active": "#dc2626",
    "danger_soft": "#2b1416",
    "danger_soft_active": "#3d1d20",
    "success": "#4ade80",
    "warning": "#fbbf24",
    "error_bg": "#341316",
    "header_bg": "#000000",
    "header_border": "#2a2a2a",
    "header_text": "#dddddd",
    "header_hover": "#141414",
    "status_bg": "#0d0d0d",
    "status_border": "#232323",
    "status_label": "#8f8f8f",
    "status_value": "#e2e2e2",
    "status_progress_bg": "rgba(255,255,255,0.12)",
    "input_bg": "#0a0a0a",
    "input_focus": "#3b82f6",
    "editor_gutter_bg": "#080808",
    "editor_gutter_border": "#232323",
    "editor_line_number": "#5c5c5c",
    "editor_current_line": "#60a5fa",
    "tooltip_bg": "#e8e8e8",
    "tooltip_text": "#0a0a0a",
    "scrollbar": "#3d3d3d",
    "scrollbar_hover": "#525252",
    "icon_fg": "#dddddd",
    "icon_muted": "#8f8f8f",
    "icon_accent": "#60a5fa",
    "icon_secondary": "#c084fc",
    "icon_success": "#4ade80",
    "icon_danger": "#f87171",
    # Фирменные цвета движков БД (светлее официальных, чтобы были
    # читаемы на чисто-чёрном фоне тёмной темы).
    "mysql_brand": "#6ea5c9",
    "mssql_brand": "#e0645f",
    "pgsql_brand": "#5892c8",
    "alt_base": "#0d0d0d",
    "sql_keyword": "#60a5fa",
    "sql_string": "#6ee7a8",
    "sql_number": "#ffb454",
    "sql_comment": "#8f8f8f",
    "sql_identifier": "#67e8f9",
    "log_info": "#60a5fa",
    "log_success": "#4ade80",
    "log_warning": "#fbbf24",
    "log_error": "#f87171",
    "log_stamp": "#8f8f8f",
    "log_text": "#cfcfcf",
}

THEMES = {"light": LIGHT, "dark": DARK}

_MODES = ("auto", "light", "dark")

_MODE = "auto"
_STATE = {"name": "light"}
_LISTENERS: list = []


# ----------------------------------------------------------
# Состояние темы
# ----------------------------------------------------------

def current_theme() -> str:
    return _STATE["name"]


def set_current_theme(name: str) -> None:
    _STATE["name"] = name if name in THEMES else "light"


def theme_colors(name: str | None = None) -> dict:
    return THEMES[name or _STATE["name"]]


def color(key: str, name: str | None = None) -> str:
    return theme_colors(name)[key]


def qcolor(key: str, name: str | None = None) -> QColor:
    return QColor(theme_colors(name)[key])


# ----------------------------------------------------------
# Статусы результатов (таблица Results)
# ----------------------------------------------------------

def status_color(status: str) -> QColor | None:
    key = {"OK": "success", "WARNING": "warning", "ERROR": "danger"}.get(status)
    if key is None:
        return None
    return QColor(theme_colors()[key])


def error_bg() -> QColor:
    return QColor(theme_colors()["error_bg"])


# ----------------------------------------------------------
# Режим темы и следование за системой
# ----------------------------------------------------------

def system_appearance() -> str:
    """Системная схема: 'light', 'dark' или 'unknown'."""
    app = QApplication.instance()
    if app is None:
        return "unknown"
    try:
        scheme = app.styleHints().colorScheme()
    except Exception:
        return "unknown"
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    return "unknown"


def resolve_theme(mode: str | None = None) -> str:
    m = mode or _MODE
    if m == "auto":
        system = system_appearance()
        if system in ("light", "dark"):
            return system
        return current_theme()
    return m


def mode() -> str:
    return _MODE


def set_mode(mode: str) -> None:
    global _MODE
    if mode not in _MODES:
        mode = "auto"
    _MODE = mode
    save_mode(mode)
    apply_theme(resolve_theme(mode))


def maybe_system_change() -> None:
    """Вызывается при изменении системной схемы: если режим «авто» —
    переключает тему. Ручные режимы игнорируются."""
    if _MODE != "auto":
        return
    resolved = resolve_theme()
    if resolved != current_theme():
        apply_theme(resolved)


# ----------------------------------------------------------
# Применение темы
# ----------------------------------------------------------

def apply_theme(name: str) -> None:
    set_current_theme(name)
    _notify_listeners()
    apply_window_appearance()


def register_theme_listener(fn) -> None:
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def unregister_theme_listener(fn) -> None:
    if fn in _LISTENERS:
        _LISTENERS.remove(fn)


def _notify_listeners() -> None:
    for fn in list(_LISTENERS):
        try:
            fn()
        except Exception:
            pass


# ----------------------------------------------------------
# Нативный заголовок окна (macOS)
# ----------------------------------------------------------

def apply_window_appearance(window=None) -> None:
    """Переключает внешность NSWindow (заголовок окна) под тему.

    macOS не связывает тему Qt с темой системного окна автоматически,
    поэтому вручную выставляем NSWindow.appearance. Вызывать после
    показа окна или при смене темы."""
    if sys.platform != "darwin":
        return
    if QGuiApplication.platformName() != "cocoa":
        return
    try:
        import ctypes
        import ctypes.util
        from PySide6.QtWidgets import QWidget

        lib_path = ctypes.util.find_library("objc") or "/usr/lib/libobjc.dylib"
        lib = ctypes.CDLL(lib_path)
        msg = lib.objc_msgSend

        def _cls(name: str):
            lib.objc_getClass.restype = ctypes.c_void_p
            lib.objc_getClass.argtypes = [ctypes.c_char_p]
            return lib.objc_getClass(name.encode())

        def _sel(name: str):
            lib.sel_registerName.restype = ctypes.c_void_p
            lib.sel_registerName.argtypes = [ctypes.c_char_p]
            return lib.sel_registerName(name.encode())

        def _send(receiver, selector, *args, restype=ctypes.c_void_p, argtypes=()):
            msg.restype = restype
            msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + list(argtypes)
            return msg(receiver, selector, *args)

        name = "NSAppearanceNameDarkAqua" if current_theme() == "dark" else "NSAppearanceNameAqua"
        nsstring = _send(
            _cls("NSString"), _sel("stringWithUTF8String:"),
            ctypes.c_char_p(name.encode()),
            restype=ctypes.c_void_p, argtypes=[ctypes.c_char_p],
        )
        appearance = _send(
            _cls("NSAppearance"), _sel("appearanceNamed:"), nsstring,
            restype=ctypes.c_void_p, argtypes=[ctypes.c_void_p],
        )
        if not appearance:
            return

        targets = [window] if window is not None else []
        if not targets:
            app = QApplication.instance()
            if app is not None:
                targets = [w for w in app.topLevelWidgets() if w is not None and w.isWindow()]
        for w in targets:
            try:
                wid = int(w.winId())
                if not wid:
                    continue
                view = ctypes.c_void_p(wid)
            except Exception:
                continue
            nswindow = _send(view, _sel("window"))
            if nswindow:
                _send(nswindow, _sel("setAppearance:"), appearance, argtypes=[ctypes.c_void_p])
    except Exception:
        pass


# ----------------------------------------------------------
# Генерация стилей
# ----------------------------------------------------------

_TEMPLATE = """
QWidget#MainWindow{
    background:{window};
}

QFrame{
    background:{card};
    border:1px solid {border};
    border-radius:10px;
}

QLabel{
    color:{text};
    background:transparent;
    border:none;
}

QLabel#SectionTitle{
    font-size:13px;
    font-weight:700;
    color:{text_secondary};
    border:none;
    border-left:3px solid {accent};
    padding:0 0 0 8px;
    background:transparent;
}

QLabel#MutedLabel{
    font-size:12px;
    color:{text_muted};
    border:none;
    background:transparent;
}

QLabel#InlineLabel{
    color:{text};
    border:none;
    background:transparent;
}

/* --- Scripts library --- */
QFrame#ScriptsListCard{
    background:{card};
    border:1px solid {border};
    border-radius:10px;
    padding:6px;
}

QListWidget#ScriptsList{
    background:{input_bg};
    color:{text};
    border:1px solid {border};
    border-radius:6px;
    padding:2px;
    outline:0;
}

QListWidget#ScriptsList::item{
    padding:4px 8px;
    border-radius:4px;
    margin:0;
}

QListWidget#ScriptsList::item:hover{
    background:{hover_bg};
}

QListWidget#ScriptsList::item:selected{
    background:{sel_bg};
    color:{sel_text};
}

QLineEdit#SearchField{
    background:{input_bg};
    border:1px solid {border};
    border-radius:7px;
    min-height:22px;
    padding:0 6px;
    color:{text};
    font-size:12px;
    selection-background-color:{accent};
    selection-color:#ffffff;
}

QLineEdit#SearchField:focus{
    border:1px solid {input_focus};
}

QLineEdit#SearchField:disabled{
    color:{text_muted};
}

/* --- Status bar (полноширинная строка внизу; цвет по теме) --- */
QFrame#StatusBar{
    background:{status_bg};
    border:none;
    border-top:1px solid {status_border};
    border-radius:0;
}

QFrame#StatusBar QLabel{
    border:none;
    background:transparent;
    font-size:12px;
}

QFrame#StatusBar QLabel#StatusCaption{
    color:{status_label};
}

QFrame#StatusBar QLabel#StatusValue{
    color:{status_value};
    font-weight:600;
}

QFrame#StatusBar QProgressBar{
    background:{status_progress_bg};
    border:none;
    border-radius:4px;
    min-height:6px;
    max-height:6px;
    text-align:center;
}

QFrame#StatusBar QProgressBar::chunk{
    background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #3b82f6, stop:1 #60a5fa);
    border-radius:4px;
}

QToolButton#ThemeToggle{
    border:none;
    border-radius:6px;
    padding:4px;
    background:transparent;
}

QToolButton#ThemeToggle:hover{
    background:rgba(255,255,255,0.14);
}

QToolButton#ThemeToggle:pressed{
    background:rgba(255,255,255,0.22);
}

/* --- Inputs --- */
QTreeWidget,
QTextEdit,
QPlainTextEdit,
QTableWidget,
QLineEdit,
QComboBox,
QAbstractSpinBox{
    background:{input_bg};
    border:1px solid {border};
    border-radius:8px;
    color:{text};
    font-size:13px;
    padding:5px;
    selection-background-color:{sel_bg};
    selection-color:{sel_text};
}

QTableWidget{
    padding:0;
    border-radius:0;
}

QTreeWidget::item{
    padding:4px 6px;
    border-radius:6px;
}

QTreeWidget::item:selected{
    background:{sel_bg};
    color:{sel_text};
    font-weight:600;
}

QTreeWidget::item:hover{
    background:{hover_bg};
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus{
    border:2px solid {accent};
}

QTreeWidget:focus,
QTableWidget:focus{
    border:1px solid {accent};
}

QComboBox{
    padding:4px 28px 4px 10px;
}

QComboBox QAbstractItemView{
    background:{card};
    border:1px solid {border};
    border-radius:8px;
    outline:none;
    padding:6px;
    selection-background-color:{sel_bg};
    selection-color:{sel_text};
}

QComboBox QAbstractItemView::item{
    border:none;
    border-radius:6px;
    padding:4px 6px;
}

QComboBox QAbstractItemView::item:hover{
    background:{hover_bg_strong};
}

QComboBox QFrame{
    background:{card};
    border:none;
    border-radius:0;
}

/* --- Селекторы сервер/БД (SQL-консоль) --- */
QComboBox#combo_select{
    background:{input_bg};
    border:1px solid {border};
    border-radius:8px;
    color:{text};
    font-size:13px;
    padding:4px 30px 4px 10px;
    min-height:22px;
    selection-background-color:{sel_bg};
    selection-color:{sel_text};
}

QComboBox#combo_select:hover{
    border-color:{border_strong};
}

QComboBox#combo_select:focus{
    border:2px solid {accent};
}

QComboBox#combo_select:disabled{
    color:{text_muted};
    background:{hover_bg};
}

QComboBox#combo_select::drop-down{
    border:none;
    width:26px;
}

/* --- Автодополнение SQL (QCompleter) --- */
QListView#CompletionPopup{
    background:{card};
    border:1px solid {border};
    border-radius:8px;
    padding:4px;
    outline:none;
}

QListView#CompletionPopup::item{
    padding:4px 8px;
    border-radius:4px;
    border:none;
    color:{text};
}

QListView#CompletionPopup::item:hover{
    background:{hover_bg_strong};
}

QListView#CompletionPopup::item:selected{
    background:{sel_bg};
    color:{sel_text};
    font-weight:600;
}

QToolBar{
    background:{card};
    border:1px solid {border};
    border-radius:10px;
    padding:4px;
    spacing:4px;
}

QToolBar::separator{
    width:1px;
    background:{divider};
    margin:4px 4px;
}

QToolBar QToolButton{
    border:none;
    border-radius:6px;
    background:transparent;
    padding:6px;
    color:{icon_muted};
    font-weight:600;
}

QToolBar QToolButton:hover{
    background:{hover_bg_strong};
    color:{text};
}

QToolBar QToolButton:pressed{
    background:{divider};
}

QToolBar QToolButton:disabled{
    color:{border_strong};
}

/* --- Icon buttons --- */
QToolButton#btn_icon{
    border:none;
    border-radius:6px;
    background:transparent;
    padding:4px 6px;
    color:{icon_muted};
}

QToolButton#btn_icon:hover{
    background:{hover_bg_strong};
    color:{accent};
}

QToolButton#btn_icon:pressed{
    background:{accent_soft_active};
}

QToolButton#btn_icon:disabled{
    background:transparent;
    color:{border_strong};
}

QToolButton#btn_icon_danger{
    border:none;
    border-radius:6px;
    background:transparent;
    padding:4px 6px;
    color:{icon_danger};
}

QToolButton#btn_icon_danger:hover{
    background:{danger_soft};
    color:{danger};
}

QToolButton#btn_icon_danger:pressed{
    background:{danger_soft_active};
}

QToolButton#btn_icon_danger:disabled{
    background:transparent;
    color:{border_strong};
}

/* --- Buttons --- */
QPushButton{
    min-height:28px;
    border:1px solid {border};
    border-radius:7px;
    background:{card};
    color:{text};
    font-weight:600;
    font-size:13px;
    text-align:center;
    padding:0 14px;
}

QPushButton:hover{
    background:{hover_bg};
    border-color:{border_strong};
    color:{text};
}

QPushButton:pressed{
    background:{hover_bg_strong};
    border-color:{text_muted};
}

QPushButton:disabled{
    background:{hover_bg};
    border-color:{divider};
    color:{text_muted};
}

QPushButton:focus{
    border:2px solid {accent};
    color:{accent};
}

QPushButton#btn_primary{
    background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {accent_top}, stop:1 {accent_bottom});
    border:1px solid {accent};
    color:white;
    font-weight:700;
}

QPushButton#btn_primary:hover{
    background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {accent_bottom}, stop:1 {accent_hover});
    border-color:{accent_hover};
    color:white;
}

QPushButton#btn_primary:pressed{
    background:{accent_active};
    border-color:{accent_active};
    color:white;
}

QPushButton#btn_primary:disabled{
    background:{hover_bg};
    border-color:{divider};
    color:{text_muted};
}

QPushButton#btn_danger{
    background:{card};
    border:1px solid {danger};
    color:{danger};
    font-weight:600;
}

QPushButton#btn_danger:hover{
    background:{danger_soft};
    border-color:{danger_hover};
    color:{danger_hover};
}

QPushButton#btn_danger:pressed{
    background:{danger_soft_active};
    border-color:{danger_active};
    color:{danger_active};
}

QPushButton#btn_danger:disabled{
    background:{hover_bg};
    border-color:{divider};
    color:{text_muted};
}

/* --- Help icon («?» в кружочке) --- */
QToolButton#HelpIcon{
    border:1px solid {border};
    border-radius:9px;
    background:{card};
    color:{text_muted};
    font-size:11px;
    font-weight:700;
    padding:0;
}

QToolButton#HelpIcon:hover{
    border-color:{accent};
    background:{accent_soft};
    color:{accent};
}

/* --- Checkbox --- */
QCheckBox{
    font-size:13px;
    color:{text};
    margin:0 6px;
}

QCheckBox::indicator{
    width:18px;
    height:18px;
    border:1px solid {border_strong};
    border-radius:5px;
    background:{card};
}

QCheckBox::indicator:hover{
    border-color:{accent};
    background:{accent_soft};
}

QCheckBox::indicator:checked{
    background:{accent};
    border-color:{accent};
}

QCheckBox::indicator:pressed{
    background:{accent_soft_active};
}

/* --- Table headers --- */
QHeaderView{
    background:{header_bg};
    border:none;
}

QHeaderView::section{
    background:{header_bg};
    border:1px solid {header_border};
    border-left:none;
    border-top:none;
    padding:8px 10px;
    font-size:12px;
    font-weight:700;
    color:{header_text};
}

/* --- Tabs --- */
QTabWidget{
    background:transparent;
    border:none;
}

QTabWidget::pane{
    border:none;
    background:transparent;
}

QStackedWidget{
    border:none;
    background:transparent;
}

QFrame#TabPage{
    border:none;
    background:transparent;
}

QTabBar{
    background:{header_bg};
    border:none;
    border-top-left-radius:10px;
    border-top-right-radius:10px;
}

QTabBar::tab{
    background:transparent;
    padding:8px 18px;
    color:{text_muted};
    border:none;
    border-bottom:3px solid transparent;
    border-radius:0;
    font-size:13px;
}

QTabBar::tab:first{
    margin-left:6px;
}

QTabBar::tab:top{
    margin-top:4px;
}

QTabBar::tab:selected{
    color:{accent};
    border-bottom:3px solid {accent};
    font-weight:700;
}

QTabBar::tab:hover:!selected{
    background:{header_hover};
    color:{text};
}

/* --- Progress (default) --- */
QProgressBar{
    border:1px solid {border};
    border-radius:5px;
    background:{card};
    text-align:center;
    min-height:20px;
}

QProgressBar::chunk{
    background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {accent_top}, stop:1 {accent_bottom});
    border-radius:4px;
}

/* --- Menu --- */
QMenu{
    background:{card};
    border:1px solid {border};
    border-radius:10px;
    padding:6px;
}

QMenu::item{
    padding:7px 24px;
    border-radius:6px;
    color:{text};
}

QMenu::item:selected{
    background:{sel_bg};
    color:{accent_hover};
    font-weight:600;
}

QMenu::separator{
    height:1px;
    background:{divider};
    margin:4px 8px;
}

/* --- Tooltip --- */
QToolTip{
    background:{tooltip_bg};
    color:{tooltip_text};
    border:none;
    border-radius:6px;
    padding:5px 9px;
    font-size:12px;
}

/* --- Splitters --- */
QSplitter{
    background:transparent;
    border:none;
}

QSplitter::handle{
    background:transparent;
    border:none;
}

/* Вертикальная ручка (разделяет лево/право): без линии — рамки панелей
   по краям уже разделяют карточки */
QSplitter::handle:horizontal{
    background:transparent;
    border:none;
}

/* Горизонтальная ручка (разделяет верх/низ): без линии — рамки панелей
   сверху/снизу уже дают разделители, линия здесь дублировала бы их */
QSplitter::handle:vertical{
    background:transparent;
    border:none;
}

/* --- Scrollbars --- */
QScrollBar:vertical{
    background:transparent;
    width:11px;
    margin:2px;
}

QScrollBar::handle:vertical{
    background:{scrollbar};
    border-radius:5px;
    min-height:30px;
}

QScrollBar::handle:vertical:hover{
    background:{scrollbar_hover};
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical{
    height:0;
}

QScrollBar:horizontal{
    background:transparent;
    height:11px;
    margin:2px;
}

QScrollBar::handle:horizontal{
    background:{scrollbar};
    border-radius:5px;
    min-width:30px;
}

QScrollBar::handle:horizontal:hover{
    background:{scrollbar_hover};
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal{
    width:0;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal{
    background:transparent;
}
"""


def build_stylesheet(name: str | None = None) -> str:
    text = _TEMPLATE
    for key, value in theme_colors(name).items():
        text = text.replace("{" + key + "}", value)
    return text


def dialog_stylesheet(name: str | None = None) -> str:
    c = theme_colors(name)
    extra = """
QDialog{
    background:{window};
}

QLabel#DialogTitle{
    font-size:15px;
    font-weight:700;
    color:{text};
}
"""
    for key, value in c.items():
        extra = extra.replace("{" + key + "}", value)
    return build_stylesheet(name) + extra


def build_palette(name: str | None = None) -> QPalette:
    c = theme_colors(name)

    p = QPalette()

    for group in (QPalette.Active, QPalette.Inactive):
        p.setColor(group, QPalette.Window, QColor(c["window"]))
        p.setColor(group, QPalette.WindowText, QColor(c["text"]))
        p.setColor(group, QPalette.Base, QColor(c["input_bg"]))
        p.setColor(group, QPalette.AlternateBase, QColor(c["alt_base"]))
        p.setColor(group, QPalette.Text, QColor(c["text"]))
        p.setColor(group, QPalette.PlaceholderText, QColor(c["text_muted"]))
        p.setColor(group, QPalette.Button, QColor(c["card"]))
        p.setColor(group, QPalette.ButtonText, QColor(c["text"]))
        p.setColor(group, QPalette.Highlight, QColor(c["accent"]))
        p.setColor(group, QPalette.HighlightedText, QColor("#ffffff"))
        p.setColor(group, QPalette.Link, QColor(c["accent"]))
        p.setColor(group, QPalette.BrightText, QColor("#ffffff"))
        p.setColor(group, QPalette.ToolTipBase, QColor(c["tooltip_bg"]))
        p.setColor(group, QPalette.ToolTipText, QColor(c["tooltip_text"]))

    p.setColor(QPalette.Disabled, QPalette.Text, QColor(c["text_muted"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(c["text_muted"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["text_muted"]))
    p.setColor(QPalette.Disabled, QPalette.Highlight, QColor(c["card_border"]))
    p.setColor(
        QPalette.Disabled,
        QPalette.HighlightedText,
        QColor("#ffffff"),
    )

    return p


# ----------------------------------------------------------
# Персистентность (QSettings в Application Support)
# ----------------------------------------------------------

def _settings() -> QSettings:
    base = (
        Path.home()
        / "Library" / "Application Support" / "Parallels SQL Admin"
    )
    base.mkdir(parents=True, exist_ok=True)
    return QSettings(str(base / "settings.ini"), QSettings.IniFormat)


def load_mode() -> str:
    settings = _settings()
    value = str(settings.value("ui/theme", "auto"))
    return value if value in _MODES else "auto"


def save_mode(mode: str) -> None:
    settings = _settings()
    settings.setValue("ui/theme", mode)
    settings.sync()


def load_security_backend() -> str:
    """Предпочтительный тип ключа для нового хранилища (раздел
    «Конфиденциальность» в настройках): master_password | file_key."""
    settings = _settings()
    value = str(settings.value("security/backend", "master_password"))
    return value if value in ("master_password", "file_key") else "master_password"


def save_security_backend(kind: str) -> None:
    settings = _settings()
    settings.setValue("security/backend", kind)
    settings.sync()


def bootstrap() -> str:
    """Инициализирует режим и тему из сохранённых значений.

    Вызывается до построения UI, чтобы стили и иконки строились
    уже в нужной теме."""
    global _MODE
    _MODE = load_mode()
    set_current_theme(resolve_theme(_MODE))
    return _MODE


# ----------------------------------------------------------
# Обратная совместимость (светлая тема по умолчанию)
# ----------------------------------------------------------

SHARED_STYLESHEET = build_stylesheet("light")

LOGIN_DIALOG_STYLESHEET = dialog_stylesheet("light")

STATUS_COLORS = {
    "OK": QColor(LIGHT["success"]),
    "WARNING": QColor(LIGHT["warning"]),
    "ERROR": QColor(LIGHT["danger"]),
}

ERROR_BG = QColor(LIGHT["error_bg"])
