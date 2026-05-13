"""User-facing LLM failures (quota, auth) surfaced to the CLI without raw tracebacks."""


class LLMRequestError(Exception):
    """Raised when an LLM API call fails in a way we can explain to the user."""
