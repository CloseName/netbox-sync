"""Template translations restricted to pfSense UI labels."""
from django import template
from ..pfsense_locale import label

register = template.Library()
register.filter('fwlabel', label)
register.simple_tag(label, name='fwlabel')


@register.filter
def fwreason(text):
    for delimiter in (' · alias ', ': '):
        field, separator, value = text.partition(delimiter)
        if separator:
            base, exception, _ = field.partition(' (исключение)')
            suffix = ' (' + label('исключение') + ')' if exception else ''
            return label(base) + suffix + separator + value
    return label(text)
