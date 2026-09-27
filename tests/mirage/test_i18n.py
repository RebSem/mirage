import string

from mirage import i18n


def _fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_same_keys_in_every_language():
    assert set(i18n.EN) == set(i18n.RU)


def test_same_placeholders_in_every_language():
    for key, en in i18n.EN.items():
        assert _fields(en) == _fields(i18n.RU[key]), key


def test_tr_formats_and_falls_back():
    i18n.set_language("ru")
    assert i18n.tr("toast_added", name="Ann") == "Лицо «Ann» добавлено"
    assert i18n.tr("no_such_key") == "no_such_key"
    i18n.set_language("en")
    assert i18n.tr("start") == "Start"
