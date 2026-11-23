"""ใช้ใน template:  {% load access %}  {% if user|can:"manage_users" %} ... {% endif %}"""
from django import template

from ..permissions import has_capability

register = template.Library()


@register.filter
def can(user, capability):
    return has_capability(user, capability)
