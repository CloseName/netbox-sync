"""Translate display labels in the active NetBox request. Snapshot values stay verbatim."""
import json
from pathlib import Path

from django.utils.functional import lazy
from django.utils.translation import get_language


_CATALOG = json.loads(Path(__file__).with_name('pfsense_labels.json').read_text(encoding='utf-8'))


def label(text):
    language = (get_language() or 'en').split('-')[0]
    return _CATALOG.get(language, _CATALOG['en']).get(text, text)


lazy_label = lazy(label, str)
