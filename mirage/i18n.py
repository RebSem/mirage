"""UI strings in English and Russian.

``tr("key", **fmt)`` returns the string for the active language. Keep both
dictionaries in sync — tests/mirage/test_i18n.py checks key parity.
"""

from __future__ import annotations

import locale
import os

EN: dict[str, str] = {
    # stage / live
    "start": "Start",
    "stop": "Stop",
    "status_ready": "Ready",
    "status_loading": "Loading models…",
    "status_warming": "Warming up…",
    "status_starting": "Starting camera…",
    "status_live": "Live",
    "status_stopping": "Stopping…",
    "status_fps": "{fps:.0f} fps",
    "live_badge": "LIVE",
    "idle_title": "Pick a face, then press Start",
    "idle_subtitle": "Zoom, Meet and OBS see you as “OBS Virtual Camera”.",
    "idle_hint_keys": "Space starts and stops · 1–9 switch faces · 0 is you",
    "no_face_in_view": "Looking for your face…",
    "loading_title": "Warming up the Neural Engine…",
    "loading_subtitle": "First start takes a few seconds.",
    # faces
    "faces": "Faces",
    "face_me": "Me",
    "face_me_hint": "Your real face — no swap",
    "add_photos": "Add",
    "random_face": "Random",
    "drop_hint": "Drop photos here to add faces",
    "empty_library": "Add a photo of a face to get started. A clear, front-facing photo works best.",
    "rename": "Rename…",
    "remove": "Remove",
    "show_in_finder": "Show in Finder",
    "rename_title": "Rename face",
    "random_name": "Random {n}",
    # look
    "look": "Look",
    "quality": "Quality",
    "quality_fast": "Fast",
    "quality_balanced": "Balanced",
    "quality_best": "Best",
    "quality_hint_fast": "Smoothest video, detects your face less often.",
    "quality_hint_balanced": "Good default for calls.",
    "quality_hint_best": "Adds face enhancement. Heavier — expect fewer fps.",
    "blend": "Blend",
    "sharpness": "Sharpness",
    "keep_mouth": "Keep my mouth",
    "keep_mouth_hint": "Uses your real mouth so talking looks natural.",
    "many_faces": "Swap everyone in view",
    "color_fix": "Fix blue tint",
    "smooth_edges": "Smooth edges",
    "mirror_preview": "Mirror preview",
    "show_fps": "Show FPS",
    "more_options": "More",
    # camera / virtual camera
    "camera": "Camera",
    "no_camera": "No camera found",
    "vcam_ready": "Zoom camera: “OBS Virtual Camera”",
    "vcam_streaming": "Sending to OBS Virtual Camera",
    "vcam_missing": "OBS Virtual Camera isn't installed",
    "vcam_help": "How to use in Zoom",
    # toasts
    "toast_added": "Added “{name}”",
    "toast_added_many": "Added {n} faces",
    "toast_no_face_photo": "No face found in “{name}”. Try a clear, front-facing photo.",
    "toast_unreadable": "“{name}” isn't an image Mirage can read.",
    "toast_removed": "Removed “{name}”",
    "toast_random_failed": "Couldn't fetch a random face. Check your internet connection.",
    "toast_camera_failed": "The camera didn't start. Check System Settings → Privacy & Security → Camera.",
    "toast_camera_lost": "The camera stopped sending video.",
    "toast_models_failed": "Models failed to load: {error}",
    "toast_models_missing": "Models are missing. Run “make install” in the Mirage folder.",
    "toast_frame_error": "A frame hiccupped — showing your camera for a moment.",
    "toast_enhancer_loading": "Loading face enhancement…",
    "toast_enhancer_failed": "Face enhancement isn't available; using Balanced.",
    "toast_vcam_unavailable": "OBS Virtual Camera isn't available — the preview still works.",
    "toast_already_running": "Mirage is already open.",
    # menus
    "menu_file": "File",
    "menu_add_photos": "Add Photos…",
    "menu_random_face": "Random Face",
    "menu_live": "Live",
    "menu_start_stop": "Start / Stop",
    "menu_mirror": "Mirror Preview",
    "menu_faces": "Faces",
    "menu_me": "Me (Real Face)",
    "menu_help": "Help",
    "menu_readme": "Mirage Guide",
    "menu_troubleshooting": "Troubleshooting",
    "menu_responsible": "Responsible Use",
    "menu_report": "Report an Issue…",
    "menu_logs": "Show Logs",
    "menu_about": "About Mirage",
    "about_text": "Mirage {version}\nA just-for-fun, macOS-native face swap built on Deep-Live-Cam.\nAGPL-3.0 · models: non-commercial use only.",
    "file_dialog_title": "Choose photos with faces",
}

RU: dict[str, str] = {
    "start": "Старт",
    "stop": "Стоп",
    "status_ready": "Готово",
    "status_loading": "Загружаю модели…",
    "status_warming": "Прогреваю модели…",
    "status_starting": "Запускаю камеру…",
    "status_live": "В эфире",
    "status_stopping": "Останавливаю…",
    "status_fps": "{fps:.0f} к/с",
    "live_badge": "ЭФИР",
    "idle_title": "Выберите лицо и нажмите «Старт»",
    "idle_subtitle": "Zoom, Meet и OBS видят вас как «OBS Virtual Camera».",
    "idle_hint_keys": "Пробел — старт и стоп · 1–9 — лица · 0 — вы",
    "no_face_in_view": "Ищу ваше лицо…",
    "loading_title": "Разогреваю Neural Engine…",
    "loading_subtitle": "Первый запуск занимает несколько секунд.",
    "faces": "Лица",
    "face_me": "Я",
    "face_me_hint": "Ваше настоящее лицо — без замены",
    "add_photos": "Добавить",
    "random_face": "Случайное",
    "drop_hint": "Перетащите фото сюда, чтобы добавить лица",
    "empty_library": "Добавьте фото лица, чтобы начать. Лучше всего — чёткое фото анфас.",
    "rename": "Переименовать…",
    "remove": "Удалить",
    "show_in_finder": "Показать в Finder",
    "rename_title": "Переименовать лицо",
    "random_name": "Случайное {n}",
    "look": "Вид",
    "quality": "Качество",
    "quality_fast": "Быстро",
    "quality_balanced": "Баланс",
    "quality_best": "Лучше",
    "quality_hint_fast": "Самое плавное видео, лицо ищется реже.",
    "quality_hint_balanced": "Хороший вариант для звонков.",
    "quality_hint_best": "Добавляет улучшение лица. Тяжелее — кадров будет меньше.",
    "blend": "Смешивание",
    "sharpness": "Резкость",
    "keep_mouth": "Сохранять мой рот",
    "keep_mouth_hint": "Оставляет ваш настоящий рот — речь выглядит естественнее.",
    "many_faces": "Менять всех в кадре",
    "color_fix": "Убрать синеву",
    "smooth_edges": "Мягкие края",
    "mirror_preview": "Зеркалить превью",
    "show_fps": "Показывать FPS",
    "more_options": "Ещё",
    "camera": "Камера",
    "no_camera": "Камера не найдена",
    "vcam_ready": "Камера для Zoom: «OBS Virtual Camera»",
    "vcam_streaming": "Идёт в OBS Virtual Camera",
    "vcam_missing": "OBS Virtual Camera не установлена",
    "vcam_help": "Как подключить в Zoom",
    "toast_added": "Добавлено «{name}»",
    "toast_added_many": "Добавлено лиц: {n}",
    "toast_no_face_photo": "На «{name}» не найдено лицо. Попробуйте чёткое фото анфас.",
    "toast_unreadable": "«{name}» — не изображение, которое Mirage может открыть.",
    "toast_removed": "Удалено «{name}»",
    "toast_random_failed": "Не удалось получить случайное лицо. Проверьте интернет.",
    "toast_camera_failed": "Камера не запустилась. Проверьте Системные настройки → Конфиденциальность и безопасность → Камера.",
    "toast_camera_lost": "Камера перестала передавать видео.",
    "toast_models_failed": "Не удалось загрузить модели: {error}",
    "toast_models_missing": "Нет моделей. Выполните «make install» в папке Mirage.",
    "toast_frame_error": "Кадр споткнулся — на секунду показываю камеру.",
    "toast_enhancer_loading": "Загружаю улучшение лица…",
    "toast_enhancer_failed": "Улучшение лица недоступно, включён режим «Баланс».",
    "toast_vcam_unavailable": "OBS Virtual Camera недоступна — превью при этом работает.",
    "toast_already_running": "Mirage уже открыт.",
    "menu_file": "Файл",
    "menu_add_photos": "Добавить фото…",
    "menu_random_face": "Случайное лицо",
    "menu_live": "Эфир",
    "menu_start_stop": "Старт / Стоп",
    "menu_mirror": "Зеркалить превью",
    "menu_faces": "Лица",
    "menu_me": "Я (настоящее лицо)",
    "menu_help": "Справка",
    "menu_readme": "Руководство Mirage",
    "menu_troubleshooting": "Решение проблем",
    "menu_responsible": "Этичное использование",
    "menu_report": "Сообщить о проблеме…",
    "menu_logs": "Показать логи",
    "menu_about": "О Mirage",
    "about_text": "Mirage {version}\nЗамена лица на macOS — просто по фану, на базе Deep-Live-Cam.\nAGPL-3.0 · модели: только некоммерческое использование.",
    "file_dialog_title": "Выберите фото с лицами",
}

LANGUAGES = {"en": EN, "ru": RU}
_active = EN


def system_language() -> str:
    """'ru' if the Mac is set to Russian, else 'en'."""
    candidates = [os.environ.get("LANG", "")]
    try:
        from Foundation import NSLocale  # macOS: the UI language, not the shell's
        candidates.insert(0, str(NSLocale.preferredLanguages()[0]))
    except Exception:
        pass
    try:
        candidates.append(locale.getlocale()[0] or "")
    except Exception:
        pass
    return "ru" if any(c.lower().startswith("ru") for c in candidates if c) else "en"


def set_language(code: str) -> str:
    """Activate 'en', 'ru' or 'auto'; returns the language actually used."""
    global _active
    lang = system_language() if code == "auto" else code
    _active = LANGUAGES.get(lang, EN)
    return lang if lang in LANGUAGES else "en"


def tr(key: str, **fmt) -> str:
    text = _active.get(key) or EN.get(key) or key
    return text.format(**fmt) if fmt else text
