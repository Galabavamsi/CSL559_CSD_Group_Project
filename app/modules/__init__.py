"""One sub-package per service in HLD section 5. Each has:

  service.py  - the business logic (plain functions that take a database session)
  router.py   - the HTTP endpoints, which only validate input and call service.py

Modules may call each other's service functions, but only inventory/service.py may write
to the stock tables.
"""
