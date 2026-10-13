"""Error type carrying a stable machine-readable code and a process exit code."""

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NO_CANDIDATE = 2
EXIT_INVALID_INPUT = 3


class PdfSignError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = EXIT_USAGE):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
