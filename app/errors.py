from app.schemas import ErrorDetail


class UpstreamServiceError(Exception):
    """A simulated upstream HTTP failure; no real HTTP integration yet."""


class BackendError(Exception):
    def __init__(self, status_code: int, detail: ErrorDetail):
        super().__init__(detail.message)
        self.status_code = status_code
        self.detail = detail


def data_error(code: str, message: str, fields: list[str] | None = None):
    status = 404 if code == "OBJECT_NOT_FOUND" else 409
    return BackendError(status, ErrorDetail(
        category="data", code=code, message=message, fields=fields or []
    ))
