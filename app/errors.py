"""One error type for business-rule failures, turned into JSON by main.py."""


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(what: str, ident) -> DomainError:
    return DomainError(404, "not_found", f"{what} {ident} does not exist")
