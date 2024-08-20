import dataclasses


@dataclasses.dataclass(frozen=True, kw_only=True)
class PyTestTypingRunnerException(Exception):
    pass
