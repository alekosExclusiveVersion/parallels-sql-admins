"""
gui/sql_highlighter.py

Подсветка синтаксиса SQL для QPlainTextEdit.
"""

import re

from PySide6.QtGui import (
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
)

from common.sql_completion import SQL_KEYWORDS
from gui.styles import qcolor


KEYWORDS = list(SQL_KEYWORDS)

KEYWORD_RE = re.compile(
    r"\b(" + "|".join(KEYWORDS) + r")\b",
    re.IGNORECASE,
)

STRING_RE = re.compile(r"(?:'[^']*'|\"[^\"]*\")")

NUMBER_RE = re.compile(r"\b\d+(\.\d+)?\b")

LINE_COMMENT_RE = re.compile(r"(--|#)[^\n]*")

MULTI_COMMENT_START_RE = re.compile(r"/\*")
MULTI_COMMENT_END_RE = re.compile(r"\*/")

IDENTIFIER_RE = re.compile(r"`[^`]*`")


class SQLHighlighter(QSyntaxHighlighter):

    def __init__(self, document):
        super().__init__(document)

        self._keyword_format = QTextCharFormat()
        self._keyword_format.setFontWeight(QFont.Bold)

        self._string_format = QTextCharFormat()

        self._number_format = QTextCharFormat()

        self._comment_format = QTextCharFormat()
        self._comment_format.setFontItalic(True)

        self._identifier_format = QTextCharFormat()

        self.retheme()

    def retheme(self):
        """Перекрашивает форматы в цвета текущей темы."""
        self._keyword_format.setForeground(qcolor("sql_keyword"))
        self._string_format.setForeground(qcolor("sql_string"))
        self._number_format.setForeground(qcolor("sql_number"))
        self._comment_format.setForeground(qcolor("sql_comment"))
        self._identifier_format.setForeground(qcolor("sql_identifier"))
        self.rehighlight()

    def highlightBlock(self, text):

        for match in LINE_COMMENT_RE.finditer(text):
            self.setFormat(
                match.start(),
                match.end() - match.start(),
                self._comment_format,
            )

        self._set_multiline_comment(text)

        for match in STRING_RE.finditer(text):
            self.setFormat(
                match.start(),
                match.end() - match.start(),
                self._string_format,
            )

        for match in NUMBER_RE.finditer(text):
            self.setFormat(
                match.start(),
                match.end() - match.start(),
                self._number_format,
            )

        for match in IDENTIFIER_RE.finditer(text):
            self.setFormat(
                match.start(),
                match.end() - match.start(),
                self._identifier_format,
            )

        for match in KEYWORD_RE.finditer(text):
            self.setFormat(
                match.start(),
                match.end() - match.start(),
                self._keyword_format,
            )

    def _set_multiline_comment(self, text):

        start = 0

        previous = self.previousBlockState()

        in_comment = (previous == 1)

        while True:

            if in_comment:

                end_match = MULTI_COMMENT_END_RE.search(
                    text,
                    start,
                )

                if end_match is None:
                    self.setFormat(
                        start,
                        len(text) - start,
                        self._comment_format,
                    )
                    self.setCurrentBlockState(1)
                    return

                self.setFormat(
                    start,
                    end_match.end() - start,
                    self._comment_format,
                )

                in_comment = False
                start = end_match.end()

            else:

                start_match = MULTI_COMMENT_START_RE.search(
                    text,
                    start,
                )

                if start_match is None:
                    self.setCurrentBlockState(0)
                    return

                end_match = MULTI_COMMENT_END_RE.search(
                    text,
                    start_match.end(),
                )

                if end_match is None:
                    self.setFormat(
                        start_match.start(),
                        len(text) - start_match.start(),
                        self._comment_format,
                    )
                    self.setCurrentBlockState(1)
                    return

                self.setFormat(
                    start_match.start(),
                    end_match.end() - start_match.start(),
                    self._comment_format,
                )

                start = end_match.end()
