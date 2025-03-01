import datetime

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using the key."""
    return dictionary.get(key, [])


@register.simple_tag
def day_of_week(day, month, year):
    """Return the day of week given day, month, and year."""
    # Convert to integers
    day = int(day)
    month = int(month)
    year = int(year)

    # Create date object
    date_obj = datetime.date(year, month, day)

    # Get day of week
    return date_obj.strftime("%A")  # Full name (Monday, Tuesday, etc.)
