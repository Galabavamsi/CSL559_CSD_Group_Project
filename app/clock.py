"""The calendar the cities live by.

The server's clock and every stored timestamp are UTC. A calendar date is another matter: a use-by date, a harvest
date and "today" belong to the place where the food is, and India is five and a half hours ahead. Taking today's
date from the server's clock would keep a pack on sale until 05:30 on the morning after its use-by date, and would
sell at the rescue price a day late. Anything that asks "what is the date" asks here.

Sales statistics (forecasting, assortment) still count days in UTC: they bucket timestamps, and moving their day
boundary would shift the history they were built from.
"""
from datetime import date, timedelta

from . import config
from .models import utcnow

LOCAL = timedelta(minutes=config.LOCAL_UTC_OFFSET_MINUTES)       # the cities' clock, ahead of UTC


def today() -> date:
    """Today's date where the hubs are."""
    return (utcnow() + LOCAL).date()
