import dataclasses
import pathlib
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Generic, Literal, cast, overload

from typing_extensions import Self, Unpack

from . import protocols


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunResult(Generic[protocols.T_Scenario]):
    """
    A concrete implementation of protocols.RunResult.
    """

    options: protocols.RunOptions[protocols.T_Scenario]
    exit_code: int
    stdout: str
    stderr: str

    @classmethod
    def from_options(
        cls,
        options: protocols.RunOptions[protocols.T_Scenario],
        exit_code: int,
        *,
        stdout: str,
        stderr: str,
    ) -> Self:
        return cls(options=options, exit_code=exit_code, stdout=stdout, stderr=stderr)


@dataclasses.dataclass(kw_only=True)
class ProgramNotice:
    """
    Represents a single notice from the static type checker
    """

    location: pathlib.Path
    line_number: int
    col: int | None
    severity: str
    tag: str | None
    msg: str

    def for_compare(self) -> Iterator[Self]:
        for line in self.msg.split("\n"):
            yield dataclasses.replace(self, msg=line)

    def clone(self, **kwargs: Unpack[protocols.ProgramNoticeCloneKwargs]) -> Self:
        return dataclasses.replace(self, **kwargs)

    def display(self) -> str:
        col = "" if self.col is None else f" col={self.col}"
        tag = "" if self.tag is None else f" tag={self.tag} "
        return f"{col} severity={self.severity} {tag}:: {self.msg}"

    def __lt__(self, other: protocols.ProgramNotice) -> bool:
        return self.display() < other.display()

    def matches(self, other: protocols.ProgramNotice) -> bool:
        same = (
            self.location == other.location
            and self.line_number == other.line_number
            and self.severity == other.severity
            and self.tag == other.tag
            and self.msg == other.msg
        )
        if not same:
            return False

        if self.col is not None or other.col is not None:
            return self.col == other.col

        return True


@dataclasses.dataclass(frozen=True, kw_only=True)
class LineNotices:
    location: pathlib.Path
    line_number: int

    notices: Sequence[protocols.ProgramNotice] = dataclasses.field(default_factory=list)

    @property
    def has_notices(self) -> bool:
        return bool(self.notices)

    def __iter__(self) -> Iterator[protocols.ProgramNotice]:
        yield from self.notices

    def add(self, notice: protocols.ProgramNotice) -> Self:
        return dataclasses.replace(self, notices=[*self.notices, notice])

    def replace(
        self,
        chooser: protocols.ProgramNoticeChooser,
        *,
        replaced: protocols.ProgramNotice,
        first_only: bool = True,
    ) -> Self:
        replacement: list[protocols.ProgramNotice] = []
        matched: bool = False
        for n in self.notices:
            if chooser(n):
                if not first_only or not matched:
                    matched = True
                    replacement.append(replaced)
                    continue
            replacement.append(n)

        return dataclasses.replace(self, notices=replacement)

    def remove(self, chooser: protocols.ProgramNoticeChooser) -> Self:
        return dataclasses.replace(self, notices=[n for n in self.notices if not chooser(n)])


@dataclasses.dataclass(frozen=True, kw_only=True)
class FileNotices:
    location: pathlib.Path
    by_line_number: Mapping[int, protocols.LineNotices] = dataclasses.field(default_factory=dict)
    name_to_line_number: Mapping[str, int] = dataclasses.field(default_factory=dict)

    @property
    def has_notices(self) -> bool:
        return any(notices for notices in self.by_line_number.values())

    def __iter__(self) -> Iterator[protocols.ProgramNotice]:
        for _, notices in sorted(self.by_line_number.items()):
            yield from notices

    def notices_for_line_number(self, line_number: int) -> protocols.LineNotices | None:
        if line_number not in self.by_line_number:
            return None

        return self.by_line_number[line_number]

    def set_line_notices(self, line_number: int, notices: protocols.LineNotices) -> Self:
        return dataclasses.replace(
            self, by_line_number={**self.by_line_number, line_number: notices}
        )

    def add_notice(self, line_number: int, notice: protocols.ProgramNotice) -> Self:
        notices = self._get_or_create_for_line_number(line_number)
        return dataclasses.replace(
            self, by_line_number={**self.by_line_number, line_number: notices.add(notice)}
        )

    def set_name(self, name: str, line_number: int) -> Self:
        return dataclasses.replace(
            self, name_to_line_number={**self.name_to_line_number, name: line_number}
        )

    def _get_or_create_for_line_number(self, line_number: int) -> protocols.LineNotices:
        if (existing := self.by_line_number.get(line_number)) is None:
            return LineNotices(line_number=line_number, location=self.location)
        else:
            return existing

    @overload
    def find_for_name_or_line(
        self, *, name_or_line: str | int, severity: str | None = None, must_exist: Literal[True]
    ) -> tuple[int, protocols.LineNotices, protocols.ProgramNotice]: ...

    @overload
    def find_for_name_or_line(
        self,
        *,
        name_or_line: str | int,
        severity: str | None = None,
        must_exist: Literal[False] = False,
    ) -> tuple[int, protocols.LineNotices, protocols.ProgramNotice | None]: ...

    def find_for_name_or_line(
        self, *, name_or_line: str | int, severity: str | None = None, must_exist: bool = False
    ) -> tuple[int, protocols.LineNotices, protocols.ProgramNotice | None]:
        if isinstance(name_or_line, int):
            line_number = name_or_line
        else:
            name = name_or_line
            if name not in self.name_to_line_number:
                raise ValueError(f"No named line: {name}")

            line_number = self.name_to_line_number[name]

        notices = self.notices_for_line_number(line_number)
        if must_exist and notices is None:
            raise ValueError(f"No existing notices for named line: {name}")

        if notices is None:
            return line_number, LineNotices(line_number=line_number, location=self.location), None

        found: protocols.ProgramNotice | None = None
        for notice in reversed(list(notices)):
            if severity is None:
                found = notice
                break

            if notice.severity == severity:
                found = notice
                break

        if must_exist and found is None:
            raise ValueError(
                f"Found no existing notice for named line/severity: {name}/{severity}"
            )

        return line_number, notices, found

    def add_reveal(self, *, name_or_line: str | int, revealed: str) -> Self:
        line_number, notices, existing = self.find_for_name_or_line(name_or_line=name_or_line)
        if existing is not None:
            return self.change_reveal(
                name_or_line=name_or_line,
                modify=lambda original: original.clone(
                    msg=f'{original.msg}\nRevealed type is "{revealed}"'
                ),
            )

        return self.set_line_notices(
            line_number,
            notices.add(
                ProgramNotice(
                    location=self.location,
                    line_number=line_number,
                    col=None,
                    tag=None,
                    severity="note",
                    msg=f'Revealed type is "{revealed}"',
                )
            ),
        )

    def change_reveal(
        self, *, name_or_line: str | int, modify: protocols.ProgramNoticeModify
    ) -> Self:
        line_number, notices, existing = self.find_for_name_or_line(
            name_or_line=name_or_line, severity="note", must_exist=True
        )
        return self.set_line_notices(
            line_number,
            notices.replace(
                lambda original: original.matches(existing), replaced=modify(existing)
            ),
        )

    def add_error(self, *, name_or_line: str | int, error_type: str, error: str) -> Self:
        line_number, notices, _ = self.find_for_name_or_line(name_or_line=name_or_line)
        return self.set_line_notices(
            line_number,
            notices.add(
                ProgramNotice(
                    location=self.location,
                    line_number=line_number,
                    col=None,
                    tag=error_type,
                    severity="error",
                    msg=error,
                )
            ),
        )

    def change_error(
        self, *, name_or_line: str | int, modify: protocols.ProgramNoticeModify
    ) -> Self:
        line_number, notices, existing = self.find_for_name_or_line(
            name_or_line=name_or_line, severity="error", must_exist=True
        )
        return self.set_line_notices(
            line_number,
            notices.replace(
                lambda original: original.matches(existing), replaced=modify(existing)
            ),
        )

    def add_note(self, *, name_or_line: str | int, note: str) -> Self:
        line_number, notices, existing = self.find_for_name_or_line(name_or_line=name_or_line)
        if existing is not None:
            return self.change_reveal(
                name_or_line=name_or_line,
                modify=lambda original: original.clone(msg=f"{original.msg}\n{note}"),
            )
        return self.set_line_notices(
            line_number,
            notices.add(
                ProgramNotice(
                    location=self.location,
                    line_number=line_number,
                    col=None,
                    tag=None,
                    severity="note",
                    msg=note,
                )
            ),
        )

    def change_note(
        self, *, name_or_line: str | int, modify: protocols.ProgramNoticeModify
    ) -> Self:
        line_number, notices, existing = self.find_for_name_or_line(
            name_or_line=name_or_line, severity="note", must_exist=True
        )
        return self.set_line_notices(
            line_number,
            notices.replace(
                lambda original: original.matches(existing), replaced=modify(existing)
            ),
        )

    def remove_notices(
        self, *, name_or_line: str | int, chooser: protocols.ProgramNoticeChooser
    ) -> Self:
        line_number, notices, _ = self.find_for_name_or_line(name_or_line=name_or_line)
        return self.set_line_notices(line_number, notices.remove(chooser))


@dataclasses.dataclass(frozen=True, kw_only=True)
class DiffFileNotices:
    by_line_number: Mapping[
        int, tuple[Sequence[protocols.ProgramNotice], Sequence[protocols.ProgramNotice]]
    ]

    def __iter__(
        self,
    ) -> Iterator[
        tuple[int, Sequence[protocols.ProgramNotice], Sequence[protocols.ProgramNotice]]
    ]:
        for line_number, (left_notices, right_notices) in sorted(self.by_line_number.items()):
            yield line_number, sorted(left_notices), sorted(right_notices)


@dataclasses.dataclass(frozen=True, kw_only=True)
class DiffNotices:
    by_file: Mapping[str, protocols.DiffFileNotices]

    def __iter__(self) -> Iterator[tuple[str, protocols.DiffFileNotices]]:
        yield from sorted(self.by_file.items())


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProgramNotices:
    notices: Mapping[pathlib.Path, protocols.FileNotices] = dataclasses.field(default_factory=dict)

    @property
    def has_notices(self) -> bool:
        return any(notices for notices in self.notices.values())

    def __iter__(self) -> Iterator[protocols.ProgramNotice]:
        for _, notices in sorted(self.notices.items()):
            yield from notices

    def diff(
        self, root_dir: pathlib.Path, other: protocols.ProgramNotices
    ) -> protocols.DiffNotices:
        by_file_left: dict[str, dict[int, list[protocols.ProgramNotice]]] = defaultdict(
            lambda: defaultdict(list)
        )
        by_file_right: dict[str, dict[int, list[protocols.ProgramNotice]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for notices, into in ((self, by_file_left), (other, by_file_right)):
            for notice in notices:
                if notice.location.is_relative_to(root_dir):
                    path = str(notice.location.relative_to(root_dir))
                else:
                    path = str(notice.location)
                into[path][notice.line_number].extend(list(notice.for_compare()))

        final: dict[
            str, dict[int, tuple[list[protocols.ProgramNotice], list[protocols.ProgramNotice]]]
        ] = defaultdict(lambda: defaultdict(lambda: ([], [])))

        for index, frm in ((0, by_file_left), (1, by_file_right)):
            for path, by_line in frm.items():
                for line_number, ns in by_line.items():
                    final[path][line_number][index].extend(ns)

        return DiffNotices(
            by_file={
                path: DiffFileNotices(by_line_number=by_line_number)
                for path, by_line_number in final.items()
            }
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Expectations(Generic[protocols.T_Scenario]):
    options: protocols.RunOptions[protocols.T_Scenario]

    expect_fail: bool
    expect_stderr: str = ""
    expect_notices: ProgramNotices = dataclasses.field(default_factory=ProgramNotices)

    def check_results(self, result: protocols.RunResult[protocols.T_Scenario]) -> None:
        self.options.runner.check_notices(result=result, expected_notices=self.expect_notices)
        assert result.stderr == self.expect_stderr
        if self.expect_fail or any(notice.severity == "error" for notice in self.expect_notices):
            assert result.exit_code != 0
        else:
            assert result.exit_code == 0

    @classmethod
    def success_expectation(
        cls,
        scenario_runner: protocols.ScenarioRunner[protocols.T_Scenario],
        options: protocols.RunOptions[protocols.T_Scenario],
    ) -> Self:
        return cls(options=options, expect_fail=False)


if TYPE_CHECKING:
    _RR: protocols.RunResult[protocols.P_Scenario] = cast(RunResult[protocols.P_Scenario], None)

    _E: protocols.P_Expectations = cast(Expectations[protocols.P_Scenario], None)

    _FN: protocols.FileNotices = cast(FileNotices, None)
    _LN: protocols.LineNotices = cast(LineNotices, None)
    _PN: protocols.ProgramNotice = cast(ProgramNotice, None)
    _DN: protocols.DiffNotices = cast(DiffNotices, None)
    _DFN: protocols.DiffFileNotices = cast(DiffFileNotices, None)
