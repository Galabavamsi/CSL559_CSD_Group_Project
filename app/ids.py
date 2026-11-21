"""Ids in requests. Every table's id is a 32-bit database integer starting at 1, so an id outside that range cannot
exist. Refusing it here (422) keeps an impossible id, say 10**20, which overflows the integer, from reaching a query
and coming back as a 500. An id that is possible but unknown is still each route's 404."""
from typing import Annotated

from fastapi import Path
from pydantic import Field

MAX_ID = 2**31 - 1
Id = Annotated[int, Field(ge=1, le=MAX_ID)]       # in a request body
PathId = Annotated[int, Path(ge=1, le=MAX_ID)]    # in the URL; for an optional query use Query(None, ge=1, le=MAX_ID)
