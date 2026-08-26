import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_ICONS = {
    "done_all": (
        "M18,7l-1.41,-1.41 -6.34,6.34 1.41,1.41L18,7z"
        "M22.24,5.59L11.66,16.17 7.48,12l-1.41,1.41L11.66,19l12,-12 -1.42,-1.41z"
        "M0.41,13.41L6,19l1.41,-1.41L1.83,12 0.41,13.41z"
    ),
    "close": (
        "M19,6.41L17.59,5 12,10.59 6.41,5 5,6.41 10.59,12 "
        "5,17.59 6.41,19 12,13.41 17.59,19 19,17.59 13.41,12z"
    ),
    "swap_horiz": (
        "M6.99,11L3,15l3.99,4v-3H14v-2H6.99v-3z"
        "M21,9l-3.99,-4v3H10v2h7.01v3L21,9z"
    ),
    "delete_outline": (
        "M6,19c0,1.1 0.9,2 2,2h8c1.1,0 2,-0.9 2,-2V7H6v12z"
        "M19,4h-3.5l-1,-1h-5l-1,1H5v2h14V4z"
    ),
    "content_copy": (
        "M16,1H4C2.9,1 2,1.9 2,3v14h2V3h12V1z"
        "M19,5H8c-1.1,0 -2,0.9 -2,2v14c0,1.1 0.9,2 2,2h11c1.1,0 2,-0.9 2,-2V7c0,-1.1 -0.9,-2 -2,-2z"
        "M19,21H8V7h11v14z"
    ),
    "download": (
        "M19,9h-4V3H9v6H5l7,7 7,-7z"
        "M5,18v2h14v-2H5z"
    ),
    "swap_vert": (
        "M16,17.01V10h-2v7.01h-3L15,21l4,-3.99h-3z"
        "M9,3L5,6.99h3V14h2V6.99h3L9,3z"
    ),
    "info_outline": (
        "M12,2C6.48,2 2,6.48 2,12s4.48,10 10,10 10,-4.48 10,-10S17.52,2 "
        "12,2zM12,20c-4.41,0 -8,-3.59 -8,-8s3.59,-8 8,-8 8,3.59 8,8 "
        "-3.59,8 -8,8zM11,7h2v2h-2zM11,11h2v6h-2z"
    ),
    "refresh": (
        "M17.65,6.35C16.2,4.9 14.21,4 12,4c-4.42,0 -7.99,3.58 -7.99,8s3.57,8 7.99,8"
        "c3.73,0 6.84,-2.55 7.73,-6h-2.08c-0.82,2.33 -3.04,4 -5.65,4 -3.31,0 -6,-2.69 "
        "-6,-6s2.69,-6 6,-6c1.66,0 3.14,0.69 4.22,1.78L13,11h7V4l-2.35,2.35z"
    ),
    "play_arrow": (
        "M8,5v14l11,-7z"
    ),
    "search": (
        "M15.5,14h-0.79l-0.28,-0.27C15.41,12.59 16,11.11 16,9.5 16,5.91 "
        "13.09,3 9.5,3S3,5.91 3,9.5 5.91,16 9.5,16c1.61,0 3.09,-0.59 "
        "4.23,-1.57l0.27,0.28v0.79l5,4.99L20.49,19l-4.99,-5z"
        "M9.5,14C7.01,14 5,11.99 5,9.5S7.01,5 9.5,5 14,7.01 14,9.5 "
        "11.99,14 9.5,14z"
    ),
    "save": (
        "M17,3H5c-1.11,0 -2,0.9 -2,2v14c0,1.1 0.89,2 2,2h14c1.1,0 "
        "2,-0.9 2,-2V7l-4,-4zM12,19c-1.66,0 -3,-1.34 -3,-3s1.34,-3 "
        "3,-3 3,1.34 3,3 -1.34,3 -3,3zM15,9H5V5h10v4z"
    ),
    "edit": (
        "M3,17.25V21h3.75L17.81,9.94l-3.75,-3.75L3,17.25z "
        "M20.71,7.04c0.39,-0.39 0.39,-1.02 0,-1.41l-2.34,-2.34"
        "c-0.39,-0.39 -1.02,-0.39 -1.41,0l-1.83,1.83 3.75,3.75 1.83,-1.83z"
    ),
    "plus": (
        "M19,13h-6v6h-2v-6H5v-2h6V5h2v6h6z"
    ),
    "minus": (
        "M19,13H5v-2h14z"
    ),
    "lock": (
        "M18,8h-1V6c0,-2.76 -2.24,-5 -5,-5S7,3.24 7,6v2H6c-1.1,0 -2,0.9 "
        "-2,2v10c0,1.1 0.9,2 2,2h12c1.1,0 2,-0.9 2,-2V10c0,-1.1 -0.9,-2 "
        "-2,-2zM12,17c-1.1,0 -2,-0.9 -2,-2s0.9,-2 2,-2 2,0.9 2,2 -0.9,2 "
        "-2,2zM15.1,8H8.9V6c0,-1.71 1.39,-3.1 3.1,-3.1 1.71,0 3.1,1.39 "
        "3.1,3.1v2z"
    ),
    "settings": (
        "M19.14,12.94c0.04,-0.3 0.06,-0.61 0.06,-0.94c0,-0.32 -0.02,-0.64 "
        "-0.07,-0.94l2.03,-1.58c0.18,-0.14 0.23,-0.41 0.12,-0.61l-1.92,-3.32"
        "c-0.12,-0.22 -0.37,-0.29 -0.59,-0.22l-2.39,0.96c-0.5,-0.38 "
        "-1.03,-0.7 -1.62,-0.94L14.4,2.81c-0.04,-0.24 -0.24,-0.41 -0.48,-0.41"
        "h-3.84c-0.24,0 -0.43,0.17 -0.47,0.41L9.25,5.35C8.66,5.59 8.12,5.92 "
        "7.63,6.29L5.24,5.33c-0.22,-0.08 -0.47,0 -0.59,0.22L2.74,8.87C2.62,9.08 "
        "2.66,9.34 2.86,9.48l2.03,1.58C4.84,11.36 4.8,11.69 4.8,12s0.02,0.64 "
        "0.07,0.94l-2.03,1.58c-0.18,0.14 -0.23,0.41 -0.12,0.61l1.92,3.32"
        "c0.12,0.22 0.37,0.29 0.59,0.22l2.39,-0.96c0.5,0.38 1.03,0.7 1.62,0.94"
        "l0.36,2.54c0.05,0.24 0.24,0.41 0.48,0.41h3.84c0.24,0 0.44,-0.17 "
        "0.47,-0.41l0.36,-2.54c0.59,-0.24 1.13,-0.56 1.62,-0.94l2.39,0.96"
        "c0.22,0.08 0.47,0 0.59,-0.22l1.92,-3.32c0.12,-0.22 0.07,-0.47 "
        "-0.12,-0.61L19.14,12.94zM12,15.6c-1.98,0 -3.6,-1.62 -3.6,-3.6"
        "s1.62,-3.6 3.6,-3.6s3.6,1.62 3.6,3.6S13.98,15.6 12,15.6z"
    ),
    "check_circle": (
        "M12,2C6.48,2 2,6.48 2,12s4.48,10 10,10 10,-4.48 10,-10S17.52,2 12,2z "
        "M10,17l-5,-5 1.41,-1.41L10,14.17l7.59,-7.59L19,8l-9,9z"
    ),
    "stop": (
        "M6,6h12v12H6z"
    ),
    "dns": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<!-- тень под ящиками -->'
        '<rect x="3.5" y="11.2" width="17" height="0.8" rx="0.4" '
        'fill="#000000" opacity="0.12"/>'
        '<!-- верхний серверный ящик -->'
        '<path fill="{c}" d="M20,2H4C2.9,2 2,2.9 2,4.5v4c0,1.1 '
        '0.9,2 2,2h16c1.1,0 2,-0.9 2,-2v-4C22,2.9 21.1,2 20,2z"/>'
        '<!-- highlight верхнего ящика -->'
        '<rect x="3" y="2.8" width="18" height="0.7" rx="0.35" '
        'fill="#ffffff" opacity="0.2"/>'
        '<rect x="3" y="3.4" width="18" height="0.4" rx="0.2" '
        'fill="#ffffff" opacity="0.08"/>'
        '<!-- зелёный LED -->'
        '<circle cx="5.5" cy="6.2" r="1.4" fill="#15803d"/>'
        '<circle cx="5.5" cy="6.2" r="1.0" fill="#4ade80"/>'
        '<circle cx="5.2" cy="5.9" r="0.35" fill="#ffffff" opacity="0.5"/>'
        '<!-- жёлтый LED -->'
        '<circle cx="8" cy="6.2" r="1.4" fill="#a16207"/>'
        '<circle cx="8" cy="6.2" r="1.0" fill="#facc15"/>'
        '<circle cx="7.7" cy="5.9" r="0.35" fill="#ffffff" opacity="0.4"/>'
        '<!-- цилиндр БД -->'
        '<ellipse cx="14.5" cy="5.8" rx="5" ry="2" fill="#ffffff" '
        'opacity="0.3"/>'
        '<path fill="#ffffff" opacity="0.3" d="M9.5,5.8v2.2c0,1.1 '
        '2.24,2 5,2s5,-0.9 5,-2V5.8C19.5,6.9 17.24,7.8 14.5,7.8'
        'S9.5,6.9 9.5,5.8z"/>'
        '<ellipse cx="14.5" cy="5.8" rx="5" ry="1.7" fill="{c}" '
        'opacity="0.55"/>'
        '<ellipse cx="13" cy="5.2" rx="2" ry="0.7" fill="#ffffff" '
        'opacity="0.18" transform="rotate(-5 13 5.2)"/>'
        '<!-- Ethernet порты (верхний ящик) -->'
        '<rect x="9.5" y="8.2" width="1.4" height="1" rx="0.2" '
        'fill="#000000" opacity="0.25"/>'
        '<rect x="11.3" y="8.2" width="1.4" height="1" rx="0.2" '
        'fill="#000000" opacity="0.25"/>'
        '<!-- нижний серверный ящик -->'
        '<path fill="{c}" d="M20,12H4c-1.1,0 -2,0.9 -2,2v4c0,1.1 '
        '0.9,2 2,2h16c1.1,0 2,-0.9 2,-2v-4C22,12.9 21.1,12 20,12z"/>'
        '<!-- highlight нижнего ящика -->'
        '<rect x="3" y="12.8" width="18" height="0.7" rx="0.35" '
        'fill="#ffffff" opacity="0.2"/>'
        '<rect x="3" y="13.4" width="18" height="0.4" rx="0.2" '
        'fill="#ffffff" opacity="0.08"/>'
        '<!-- зелёный LED -->'
        '<circle cx="5.5" cy="16.2" r="1.4" fill="#15803d"/>'
        '<circle cx="5.5" cy="16.2" r="1.0" fill="#4ade80"/>'
        '<circle cx="5.2" cy="15.9" r="0.35" fill="#ffffff" opacity="0.5"/>'
        '<!-- жёлтый LED -->'
        '<circle cx="8" cy="16.2" r="1.4" fill="#a16207"/>'
        '<circle cx="8" cy="16.2" r="1.0" fill="#facc15"/>'
        '<circle cx="7.7" cy="15.9" r="0.35" fill="#ffffff" opacity="0.4"/>'
        '<!-- слоты дисков -->'
        '<rect x="10.5" y="14.5" width="8.5" height="0.9" rx="0.3" '
        'fill="#000000" opacity="0.2"/>'
        '<rect x="10.5" y="15.8" width="8.5" height="0.9" rx="0.3" '
        'fill="#000000" opacity="0.2"/>'
        '<rect x="10.5" y="17.1" width="8.5" height="0.9" rx="0.3" '
        'fill="#000000" opacity="0.2"/>'
        '<!-- вентиляция -->'
        '<rect x="11" y="18.5" width="6" height="0.5" rx="0.25" '
        'fill="#ffffff" opacity="0.45"/>'
        '<rect x="11" y="19.2" width="6" height="0.5" rx="0.25" '
        'fill="#ffffff" opacity="0.45"/>'
        '</svg>'
    ),
    "account_tree": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<!-- голова слона -->'
        '<ellipse cx="12" cy="11" rx="8.5" ry="9" fill="{c}"/>'
        '<ellipse cx="12" cy="11" rx="8.5" ry="9" fill="#ffffff" '
        'opacity="0.08"/>'
        '<!-- ухо (левое) -->'
        '<ellipse cx="4.5" cy="8" rx="4" ry="5.5" fill="{c}" '
        'opacity="0.85" transform="rotate(-15 4.5 8)"/>'
        '<ellipse cx="4.5" cy="8" rx="2.5" ry="3.5" fill="#ffffff" '
        'opacity="0.12" transform="rotate(-15 4.5 8)"/>'
        '<!-- ухо (правое) -->'
        '<ellipse cx="19.5" cy="8" rx="4" ry="5.5" fill="{c}" '
        'opacity="0.85" transform="rotate(15 19.5 8)"/>'
        '<ellipse cx="19.5" cy="8" rx="2.5" ry="3.5" fill="#ffffff" '
        'opacity="0.12" transform="rotate(15 19.5 8)"/>'
        '<!-- хобот -->'
        '<path fill="{c}" d="M10,14c0,0 -1,3 -1,5c0,1.1 0.9,2 2,2'
        's2,-0.9 2,-2c0,-2 -1,-5 -1,-5" opacity="0.9"/>'
        '<path fill="#ffffff" opacity="0.1" d="M10.8,14.5c0,0 -0.5,2.5 '
        '-0.5,4c0,0.6 0.4,1 1,1s1,-0.4 1,-1c0,-1.5 -0.5,-4 -0.5,-4"/>'
        '<!-- глаза -->'
        '<circle cx="8.5" cy="9.5" r="1.8" fill="#ffffff"/>'
        '<circle cx="15.5" cy="9.5" r="1.8" fill="#ffffff"/>'
        '<circle cx="8.8" cy="9.7" r="1.1" fill="#1a1a2e"/>'
        '<circle cx="15.8" cy="9.7" r="1.1" fill="#1a1a2e"/>'
        '<circle cx="9.1" cy="9.2" r="0.4" fill="#ffffff"/>'
        '<circle cx="16.1" cy="9.2" r="0.4" fill="#ffffff"/>'
        '<!-- бивни -->'
        '<path stroke="#ffffff" stroke-width="1.2" fill="none" '
        'opacity="0.85" stroke-linecap="round" '
        'd="M9,16.5c-0.5,1.5 -0.8,3.5 0,4.5"/>'
        '<path stroke="#ffffff" stroke-width="1.2" fill="none" '
        'opacity="0.85" stroke-linecap="round" '
        'd="M15,16.5c0.5,1.5 0.8,3.5 0,4.5"/>'
        '</svg>'
    ),
    "server": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<path fill="{c}" d="M20,3H4c-1.1,0 -2,0.9 -2,2v4c0,1.1 0.9,2 2,2h16'
        'c1.1,0 2,-0.9 2,-2V5c0,-1.1 -0.9,-2 -2,-2z"/>'
        '<path fill="{c}" d="M20,13H4c-1.1,0 -2,0.9 -2,2v4c0,1.1 0.9,2 2,2h16'
        'c1.1,0 2,-0.9 2,-2v-4c0,-1.1 -0.9,-2 -2,-2z"/>'
        '<circle fill="#ffffff" cx="7" cy="7" r="1.6"/>'
        '<circle fill="#ffffff" cx="7" cy="17" r="1.6"/>'
        '<rect x="10" y="5.2" width="8" height="1.6" rx="0.8" '
        'fill="#ffffff" opacity="0.85"/>'
        '<rect x="10" y="15.2" width="8" height="1.6" rx="0.8" '
        'fill="#ffffff" opacity="0.85"/>'
        '</svg>'
    ),
    "storage": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<path fill="{c}" fill-rule="evenodd" d="M21,6C21,4.34 16.97,3 12,3'
        'C7.03,3 3,4.34 3,6L3,18C3,19.66 7.03,21 12,21C16.97,21 21,19.66 '
        '21,18Z M21,9.4L3,9.4L3,8.2L21,8.2Z '
        'M21,15.8L3,15.8L3,14.6L21,14.6Z"/>'
        '</svg>'
    ),
    "grid_on": (
        "M4,8h4V4H4V8z M10,8h4V4h-4V8z M16,8h4V4h-4V8z M4,14h4v-4H4V14z "
        "M10,14h4v-4h-4V14z M16,14h4v-4h-4V14z M4,20h4v-4H4V20z "
        "M10,20h4v-4h-4V20z M16,20h4v-4h-4V20z"
    ),
    "app_icon": (
        "M3,5C3,3.9 3.9,3 5,3h14c1.1,0 2,0.9 2,2v14c0,1.1 -0.9,2 -2,2"
        "H5c-1.1,0 -2,-0.9 -2,-2V5z M5,5v3h14V5H5z M5,10v3h14v-3H5z"
        "M5,15v4h14v-4H5z M12,12l3,3 -1.5,0.5 0.5,1.5 -3,-3 1,-2z"
    ),
    "add": (
        "M19,13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"
    ),
    "light_mode": (
        "M12,7c-2.76,0,-5,2.24,-5,5s2.24,5,5,5s5,-2.24,5,-5S14.76,7,12,7L12,7z"
        "M2,13l2,0c0.55,0,1,-0.45,1,-1s-0.45,-1,-1,-1l-2,0c-0.55,0,-1,0.45,"
        "-1,1S1.45,13,2,13z M20,13l2,0c0.55,0,1,-0.45,1,-1s-0.45,-1,-1,-1l-2,0"
        "c-0.55,0,-1,0.45,-1,1S19.45,13,20,13z M11,2v2c0,0.55,0.45,1,1,1s1,"
        "-0.45,1,-1V2c0,-0.55,-0.45,-1,-1,-1S11,1.45,11,2z M11,20v2c0,0.55,"
        "0.45,1,1,1s1,-0.45,1,-1v-2c0,-0.55,-0.45,-1,-1,-1S11,19.45,11,20z "
        "M5.99,4.58c-0.39,-0.39,-1.03,-0.39,-1.41,0c-0.39,0.39,-0.39,1.03,0,"
        "1.41l1.06,1.06c0.39,0.39,1.03,0.39,1.41,0s0.39,-1.03,0,-1.41L5.99,"
        "4.58z M18.36,16.95c-0.39,-0.39,-1.03,-0.39,-1.41,0c-0.39,0.39,-0.39,"
        "1.03,0,1.41l1.06,1.06c0.39,0.39,1.03,0.39,1.41,0c0.39,-0.39,0.39,"
        "-1.03,0,-1.41L18.36,16.95z M19.42,5.99c0.39,-0.39,0.39,-1.03,0,-1.41"
        "c-0.39,-0.39,-1.03,-0.39,-1.41,0l-1.06,1.06c-0.39,0.39,-0.39,1.03,0,"
        "1.41s1.03,0.39,1.41,0L19.42,5.99z M7.05,18.36c0.39,-0.39,0.39,-1.03,"
        "0,-1.41c-0.39,-0.39,-1.03,-0.39,-1.41,0l-1.06,1.06c-0.39,0.39,-0.39,"
        "1.03,0,1.41s1.03,0.39,1.41,0L7.05,18.36z"
    ),
    "dark_mode": (
        "M9.37,5.51C9.19,6.15,9.1,6.82,9.1,7.5c0,4.08,3.32,7.4,7.4,7.4"
        "c0.68,0,1.35,-0.09,1.99,-0.27C17.45,17.19,14.93,19,12,19c-3.86,0,"
        "-7,-3.14,-7,-7C5,9.07,6.81,6.55,9.37,5.51z M12,3c-4.97,0,-9,4.03,"
        "-9,9s4.03,9,9,9s9,-4.03,9,-9c0,-0.46,-0.04,-0.92,-0.1,-1.36c-0.98,"
        "1.37,-2.58,2.26,-4.4,2.26c-2.98,0,-5.4,-2.42,-5.4,-5.4c0,-1.81,"
        "0.89,-3.42,2.26,-4.4C12.92,3.04,12.46,3,12,3L12,3z"
    ),
    "auto_mode": (
        "M12,3c-4.97,0,-9,4.03,-9,9s4.03,9,9,9S21,16.97,21,12S16.97,3,12,3z"
        "M12,19c-3.86,0,-7,-3.14,-7,-7s3.14,-7,7,-7V19z"
    ),
    "table": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<path fill="{c}" fill-rule="evenodd" d="M22.5,3.5 a2,2 0 0 0 -2,-2 '
        'h-17 a2,2 0 0 0 -2,2 v17 a2,2 0 0 0 2,2 h17 a2,2 0 0 0 2,-2 z '
        'M8,8 h0.8 v14.5 h-0.8 z M15.2,8 h0.8 v14.5 h-0.8 z '
        'M1.5,8 h21 v0.8 h-21 z M1.5,15.2 h21 v0.8 h-21 z"/>'
        '<path fill="#ffffff" opacity="0.6" d="M1.5,3.5 a2,2 0 0 1 2,-2 '
        'h17 a2,2 0 0 1 2,2 v4.5 h-21 z"/>'
        '</svg>'
    ),
    # Альтернативный набор в стиле Navicat (монитор, цилиндр, грид) —
    # для сравнения; к дереву пока не подключён.
    "server_nav": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<rect x="3" y="2" width="18" height="14" rx="1.5" fill="{c}"/>'
        '<rect x="5" y="4" width="14" height="1.3" rx="0.65" '
        'fill="#ffffff" opacity="0.8"/>'
        '<rect x="5" y="6.5" width="8" height="1" rx="0.5" '
        'fill="#ffffff" opacity="0.45"/>'
        '<path d="M10,16 h4 v3 h-4 z" fill="{c}"/>'
        '<rect x="6.5" y="19" width="11" height="2.2" rx="1.1" fill="{c}"/>'
        '</svg>'
    ),
    "storage_nav": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<path fill="{c}" d="M21,7C21,5.34 16.97,4 12,4C7.03,4 3,5.34 3,7'
        'L3,17C3,18.66 7.03,20 12,20C16.97,20 21,18.66 21,17Z"/>'
        '<ellipse cx="12" cy="6" rx="9" ry="2.8" fill="#ffffff" opacity="0.16"/>'
        '<path d="M3,7C3,8.66 7.03,10 12,10C16.97,10 21,8.66 21,7" '
        'fill="none" stroke="#ffffff" stroke-width="0.9" opacity="0.45"/>'
        '<rect x="5.5" y="8.5" width="2.2" height="8.5" rx="1.1" '
        'fill="#ffffff" opacity="0.28"/>'
        '</svg>'
    ),
    "table_nav": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        'viewBox="0 0 24 24">'
        '<rect x="1.5" y="1.5" width="21" height="21" rx="2" fill="{c}"/>'
        '<path d="M8,2.5 v19 M15.5,2.5 v19 M2,8 h20 M2,15.5 h20" '
        'stroke="#ffffff" stroke-width="0.9" opacity="0.75"/>'
        '</svg>'
    ),
    "detach": (
        "M3.9,12c0,-1.71 1.39,-3.1 3.1,-3.1h4V7H7C4.24,7 2,9.24 2,12"
        "s2.24,5 5,5h4v-1.9H7c-1.71,0 -3.1,-1.39 -3.1,-3.1z"
        "M17,7h-4v1.9h4c1.71,0 3.1,1.39 3.1,3.1s-1.39,3.1 -3.1,3.1"
        "h-4V17h4c2.76,0 5,-2.24 5,-5s-2.24,-5 -5,-5z"
        "M12.29,10.46l-1.41,1.41 1.41,1.41 1.41,-1.41z"
    ),
    "attach": (
        "M3.9,12c0,-1.71 1.39,-3.1 3.1,-3.1h4V7H7C4.24,7 2,9.24 2,12"
        "s2.24,5 5,5h4v-1.9H7c-1.71,0 -3.1,-1.39 -3.1,-3.1z"
        "M17,7h-4v1.9h4c1.71,0 3.1,1.39 3.1,3.1s-1.39,3.1 -3.1,3.1"
        "h-4V17h4c2.76,0 5,-2.24 5,-5s-2.24,-5 -5,-5z"
    ),
    "restore": (
        "M17.65,6.35C16.2,4.9 14.21,4 12,4c-4.42,0 -7.99,3.58 -7.99,8"
        "s3.57,8 7.99,8c3.73,0 6.84,-2.55 7.73,-6h-2.08c-0.82,2.33"
        "-3.04,4 -5.65,4 -3.31,0 -6,-2.69 -6,-6s2.69,-6 6,-6"
        "c1.66,0 3.14,0.69 4.22,1.78L13,11h7V4l-2.35,2.35z"
    ),
    "sqlite": (
        "M14,2H6C4.9,2 4,2.9 4,4v16c0,1.1 0.9,2 2,2h12c1.1,0 "
        "2,-0.9 2,-2V8L14,2z M6,20V4h7v5h5v11H6z"
    ),
}

# Иконки могут задаваться токеном "@ключ" — цвет резолвится из текущей
# темы (см. gui.styles). По умолчанию используется токен muted.
_ICON_THEME: dict = {}


_ENGINE_ICON_COLORS = {
    "mysql": "@mysql_brand",
    "mssql": "@mssql_brand",
    "pgsql": "@pgsql_brand",
    "sqlite": "@sqlite_brand",
}


def engine_icon_color(engine: str) -> str:
    """Токен темы для фирменного цвета иконки движка СУБД.

    MySQL — синий, MSSQL — красный, PostgreSQL — синий (#336791);
    для неизвестного движка — акцент темы (как в дереве серверов).
    """
    return _ENGINE_ICON_COLORS.get(str(engine or "").lower(), "@icon_accent")


def set_icon_theme(colors: dict) -> None:
    """Устанавливает палитру иконок из цветовых токенов текущей темы."""
    _ICON_THEME.clear()
    _ICON_THEME.update(colors or {})
    _PIXMAP_CACHE.clear()


def _resolve_color(color: str) -> str:
    if color.startswith("@"):
        return _ICON_THEME.get(color[1:], color)
    return color


# Кэш готовых QIcon: иконки рендерятся один раз на (имя, размер, цвет)
# и переиспользуются. Очищается при смене темы (set_icon_theme).
_PIXMAP_CACHE: dict[tuple, QIcon] = {}


def icon(name: str, size: int = 16, color: str = "@icon_muted") -> QIcon:
    key = (name, size, color)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached

    color = _resolve_color(color)
    entry = _ICONS[name]
    if entry.startswith("<"):
        svg = entry.format(s=size, c=color)
    else:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
            'viewBox="0 0 24 24">'
            '<path fill="{c}" d="{d}"/></svg>'
        ).format(s=size, c=color, d=entry)

    data = QByteArray(svg.encode("utf-8"))
    renderer = QSvgRenderer(data)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    result = QIcon(pixmap)
    _PIXMAP_CACHE[key] = result
    return result


_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def app_icon() -> QIcon:
    """Иконка приложения для окна, Dock/панели задач и переключателя.

    macOS: приоритет у ParallelsSQLAdmin.icns — той же иконки, что лежит
    в бандле и видна в Finder (QApplication.setWindowIcon() переопределяет
    иконку в Dock, поэтому она должна совпадать с бандл-иконкой).
    Windows: Qt не читает .icns, поэтому берём многоразмерный .ico.
    Linux: SVG/PNG (в сборку включены через datas).
    """
    icns_path = _ASSETS_DIR / "ParallelsSQLAdmin.icns"
    if sys.platform == "darwin" and icns_path.exists():
        icon = QIcon(str(icns_path))
        if not icon.isNull():
            return icon

    ico_path = _ASSETS_DIR / "ParallelsSQLAdmin.ico"
    if sys.platform == "win32" and ico_path.exists():
        icon = QIcon(str(ico_path))
        if not icon.isNull():
            return icon

    png_path = _ASSETS_DIR / "app_icon.png"

    if png_path.exists():
        return QIcon(str(png_path))

    # Фallback: монохромная встроенная иконка
    return icon("app_icon", size=64, color="#2563eb")
