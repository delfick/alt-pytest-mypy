import dataclasses
import itertools
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Generic, cast

from typing_extensions import Self

from . import notices, protocols


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunResult:
    """
    A concrete implementation of protocols.RunResult.
    """

    exit_code: int
    stdout: str
    stderr: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class Expectations(Generic[protocols.T_Scenario]):
    expect_fail: bool = False
    expect_stderr: str = ""
    expect_notices: protocols.ProgramNotices = dataclasses.field(
        default_factory=notices.ProgramNotices
    )

    def check(self, *, notice_checker: protocols.NoticeChecker[protocols.T_Scenario]) -> None:
        notice_checker.check(self.expect_notices)

        result = notice_checker.result
        assert result.stderr == self.expect_stderr
        if self.expect_fail or any(
            notice.severity == notices.ErrorSeverity("") for notice in self.expect_notices
        ):
            assert result.exit_code != 0
        else:
            assert result.exit_code == 0

    @classmethod
    def setup_for_success(
        cls, *, options: protocols.RunOptions[protocols.T_Scenario]
    ) -> type[Self]:
        return cls


def normalise_notices(
    notices: Sequence[protocols.ProgramNotice],
) -> Iterator[protocols.ProgramNotice]:
    for notice in sorted(notices):
        if "\n" in notice.msg:
            for line in notice.msg.split("\n"):
                yield notice.clone(msg=line)
        else:
            yield notice


def compare_notices(diff: protocols.DiffNotices) -> None:
    tick = "✓"
    cross = "✘"

    msg: list[str] = []
    different: bool = False

    for path, fdiff in diff:
        msg.append(f"> {path}")
        for line_number, left_notices, right_notices in fdiff:
            left_notices = list(normalise_notices(left_notices))
            right_notices = list(normalise_notices(right_notices))

            for_line: list[str | tuple[str, str]] = []

            for left, right in itertools.zip_longest(left_notices, right_notices):
                if left is None or right is None:
                    for_line.append(
                        (
                            "<NONE>" if left is None else left.display(),
                            "<NONE>" if right is None else right.display(),
                        )
                    )
                    continue

                if right.matches(left):
                    for_line.append(left.display())
                else:
                    for_line.append((left.display(), right.display()))

            prefix = "  | "
            line_check = tick if all(isinstance(m, str) for m in for_line) else cross
            if line_check == cross:
                different = True

            if len(for_line) == 1 and isinstance(for_line[0], str):
                msg.append(f"{prefix}{line_check} {line_number}:")
                msg[-1] = f"{msg[-1]} {for_line[0]}"
            else:
                msg.append(f"{prefix}{line_check} {line_number}:")
                for same_or_different in for_line:
                    if isinstance(same_or_different, str):
                        msg.append(f"{prefix}{tick} {same_or_different}")
                    else:
                        msg.append(f"{prefix}{cross} !! GOT  !! {same_or_different[0]}")
                        msg.append(f"{prefix}  !! WANT !! {same_or_different[1]}")

    if different:
        raise AssertionError("\n" + "\n".join(msg))


if TYPE_CHECKING:
    _RR: protocols.RunResult = cast(RunResult, None)

    _E: protocols.P_Expectations = cast(Expectations[protocols.P_Scenario], None)
