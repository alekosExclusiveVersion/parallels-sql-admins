from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QSplitterHandle


class CollapsibleSplitterHandle(QSplitterHandle):
    """Ручка QSplitter с обработкой двойного клика."""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event) -> None:
        # Используем штатную отрисовку Qt: ручная отрисовка splitter handle
        # на macOS/PySide6 может приводить к конфликту QPainter и падению.
        super().paintEvent(event)


class CollapsibleSplitter(QSplitter):
    """QSplitter, в котором двойной клик по ручке сворачивает секцию."""

    sectionDoubleClicked = Signal(int)

    def __init__(self, orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self._saved_sizes: dict[int, int] = {}
        # QSplitter создаёт служебную ручку с индексом 0, поэтому первая
        # видимая ручка должна получить индекс 1.
        self._next_handle_index = 0
        self.setChildrenCollapsible(True)
        self.splitterMoved.connect(self._remember_sizes)

    def createHandle(self) -> QSplitterHandle:
        handle = CollapsibleSplitterHandle(self.orientation(), self)
        handle._handle_index = self._next_handle_index
        self._next_handle_index += 1
        handle.setToolTip(
            "Перетащите — изменить размер · "
            "Двойной клик — свернуть/развернуть"
        )
        handle.doubleClicked.connect(
            lambda handle=handle: self._handle_double_clicked(handle)
        )
        return handle

    def section_for_handle(self, handle_index: int) -> int:
        """Возвращает панель, связанную с конкретной ручкой."""
        if self.orientation() == Qt.Horizontal:
            return 0
        if self.count() == 3 and handle_index == 2:
            return 2
        return max(0, handle_index - 1)

    def is_section_collapsed(self, index: int) -> bool:
        return 0 <= index < self.count() and self.sizes()[index] == 0

    def _remember_sizes(self, *args) -> None:
        for index, size in enumerate(self.sizes()):
            if size > 0:
                self._saved_sizes[index] = size

    def setSizes(self, sizes) -> None:
        """Запоминает внешние размеры до их возможного изменения Qt."""
        super().setSizes(sizes)
        self._remember_sizes()

    def _handle_double_clicked(self, handle: CollapsibleSplitterHandle) -> None:
        index = self.section_for_handle(handle._handle_index)
        if not 0 <= index < self.count():
            return

        sizes = self.sizes()
        if sizes[index] > 0:
            self._remember_sizes()
            collapsed_sizes = list(sizes)
            collapsed_sizes[index] = 0
            super().setSizes(collapsed_sizes)
        else:
            restored = self._saved_sizes.get(index, 0)
            if restored <= 0:
                available_size = (
                    self.width()
                    if self.orientation() == Qt.Horizontal
                    else self.height()
                )
                restored = max(
                    100,
                    available_size // max(2, self.count()),
                )
            sizes[index] = restored
            super().setSizes(sizes)
            self._remember_sizes()

        self.sectionDoubleClicked.emit(index)
        self.update()
        for child in self.findChildren(CollapsibleSplitterHandle):
            child.update()
