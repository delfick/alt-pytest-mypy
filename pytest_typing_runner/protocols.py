from __future__ import annotations

import enum
import pathlib
from collections.abc import Iterator, MutableMapping, MutableSequence, Sequence
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, TypeVar, cast, overload

from typing_extensions import NotRequired, Self, Unpack

T_Scenario = TypeVar("T_Scenario", bound="Scenario")
T_CO_Scenario = TypeVar("T_CO_Scenario", bound="Scenario", covariant=True)
T_CO_ScenarioFile = TypeVar("T_CO_ScenarioFile", bound="P_ScenarioFile", covariant=True)


class Strategy(enum.Enum):
    """
    The caching strategy used by the plugin

    MYPY_NO_INCREMENTAL
      - mypy is run only once for each run with --no-incremental

    MYPY_INCREMENTAL
      - mypy is run twice for each run with --incremental.
      - First with an empty cache relative to the temporary directory
      - and again after that cache is made.

    MYPY_DAEMON
      - A new dmypy is started and run twice for each run
    """

    MYPY_NO_INCREMENTAL = "MYPY_NO_INCREMENTAL"
    MYPY_INCREMENTAL = "MYPY_INCREMENTAL"
    MYPY_DAEMON = "MYPY_DAEMON"


class RunOptions(Protocol[T_Scenario]):
    """
    Used to represent the options used to run a type checker. This is a mutable object
    so that the scenario runner may modify it before it is used
    """

    scenario: T_Scenario
    typing_strategy: Strategy
    cwd: pathlib.Path
    runner: ProgramRunner[T_Scenario]
    args: MutableSequence[str]
    check_paths: MutableSequence[str]
    do_followup: bool
    environment_overrides: MutableMapping[str, str | None]


class FileModifier(Protocol):
    """
    Represents a function that can change a file in the scenario

    Implementations should aim to consider the signature as follows:

    :param path: A string representing the path from the root dir to a file
    :param content:
        Passed in as ``None`` if the file is to be deleted, otherwise the content
        to override the file with
    """

    def __call__(self, *, path: str, content: str | None) -> None: ...


class RunResult(Protocol[T_Scenario]):
    """
    Used to represent the options used to run a type checker and the result from doing so
    """

    @property
    def options(self) -> RunOptions[T_Scenario]:
        """
        The scenario that is being tested
        """

    @property
    def exit_code(self) -> int:
        """
        The exit code from running the type checker
        """

    @property
    def stdout(self) -> str:
        """
        The stdout from running the type checker
        """

    @property
    def stderr(self) -> str:
        """
        The stderr from running the type checker
        """


class RunnerConfig(Protocol):
    """
    An object to represent all the options relevant to this pytest plugin

    A default implementation is provided by ``pytest_typing_runner.RunnerConfig``
    """

    @property
    def same_process(self) -> bool:
        """
        Set by the --same-process option.

        Used to know if the type checker should be run in the same process or not.
        """

    @property
    def typing_strategy(self) -> Strategy:
        """
        Set by the --typing-strategy option.

        Used to know what type checker should be used and how.
        """


class ProgramRunner(Protocol[T_Scenario]):
    """
    Used to run the static type checker
    """

    def run(self, options: RunOptions[T_Scenario]) -> RunResult[T_Scenario]:
        """
        Run the static type checker and return a result
        """

    def check_notices(
        self,
        *,
        result: RunResult[T_Scenario],
        expected_notices: ProgramNotices,
    ) -> None:
        """
        Used to check the output against the notices in the expectations
        """

    def short_display(self) -> str:
        """
        Return a string to represent the command that was run
        """


class ScenarioRun(Protocol[T_Scenario]):
    """
    Used to hold information about a single run of a type checker
    """

    @property
    def is_first(self) -> bool:
        """
        Whether this is the first run for this scenario
        """

    @property
    def is_followup(self) -> bool:
        """
        Whether this is a followup run
        """

    @property
    def scenario(self) -> T_Scenario:
        """
        The scenario that was run
        """

    @property
    def file_modifications(self) -> Sequence[tuple[str, str]]:
        """
        The file modifications that were done before this run
        """

    @property
    def options(self) -> RunOptions[T_Scenario]:
        """
        The options that were used for the run
        """

    @property
    def result(self) -> RunResult[T_Scenario]:
        """
        The result from running the type checker
        """

    @property
    def expectations(self) -> Expectations[T_Scenario]:
        """
        The expectations that were used on this run
        """

    @property
    def expectation_error(self) -> Exception | None:
        """
        Any error from matching the result to the expectations for that run
        """

    def for_report(self) -> Iterator[str]:
        """
        Used to yield strings returned to present in the pytest report
        """


class ScenarioRuns(Protocol[T_Scenario]):
    """
    Represents information to return in a pytest report at the end of the test

    A default implementation is provided by ``pytest_typing_runner.ScenarioRuns``
    """

    @property
    def has_runs(self) -> bool:
        """
        Whether there were any runs to report
        """

    @property
    def scenario(self) -> T_Scenario:
        """
        The scenario these runs belong to
        """

    def for_report(self) -> Iterator[str]:
        """
        Used to yield strings to place into the pytest report
        """

    def add_file_modification(self, path: str, action: str) -> None:
        """
        Used to record a file modification for the next run
        """

    def add_run(
        self,
        *,
        options: RunOptions[T_Scenario],
        result: RunResult[T_Scenario],
        expectations: Expectations[T_Scenario],
        expectation_error: Exception | None,
    ) -> ScenarioRun[T_Scenario]:
        """
        Used to add a single run to the record
        """


class ProgramNoticeCloneKwargs(TypedDict):
    line_number: NotRequired[int]
    col: NotRequired[int | None]
    severity: NotRequired[str]
    tag: NotRequired[str | None]
    msg: NotRequired[str]


class ProgramNotice(Protocol):
    """
    Represents a single notice from the static type checker
    """

    @property
    def location(self) -> pathlib.Path:
        """
        The file this notice is contained in
        """

    @property
    def line_number(self) -> int:
        """
        The line number this notice appears on
        """

    @property
    def col(self) -> int | None:
        """
        The column this notice is found on, if one is provided
        """

    @property
    def severity(self) -> str:
        """
        The severity of the notice
        """

    @property
    def tag(self) -> str | None:
        """
        The tag associated with the notice if there was one
        """

    @property
    def msg(self) -> str:
        """
        The message attached to the notice, dedented and including newlines
        """

    def clone(self, **kwargs: Unpack[ProgramNoticeCloneKwargs]) -> Self:
        """
        Return a clone with specific changes
        """

    def __lt__(self, other: ProgramNotice) -> bool:
        """
        Make Program notices Orderable
        """

    def matches(self, other: ProgramNotice) -> bool:
        """
        Return whether this matches the provided notice
        """

    def display(self) -> str:
        """
        Return a string form for display
        """


class ProgramNoticeModify(Protocol):
    """
    Used to modify a program notice
    """

    def __call__(self, notice: ProgramNotice) -> ProgramNotice: ...


class ProgramNoticeChooser(Protocol):
    """
    Used to choose program notices
    """

    def __call__(self, notice: ProgramNotice) -> bool: ...


class DiffFileNotices(Protocol):
    """
    Represents the left/right of a diff between notices for a file
    """

    def __iter__(
        self,
    ) -> Iterator[tuple[int, Sequence[ProgramNotice], Sequence[ProgramNotice]]]: ...


class DiffNotices(Protocol):
    """
    Represents the difference between two ProgramNotices per file
    """

    def __iter__(self) -> Iterator[tuple[str, DiffFileNotices]]: ...


class LineNotices(Protocol):
    """
    Represents the information returned by the static type checker for a specific line in a file
    """

    @property
    def line_number(self) -> int:
        """
        The line number these notices are for
        """

    @property
    def location(self) -> pathlib.Path:
        """
        The path to this file as represented by the type checker
        """

    @property
    def has_notices(self) -> bool:
        """
        Whether this has any notices
        """

    def __iter__(self) -> Iterator[ProgramNotice]:
        """
        Yield all the notices
        """

    def add(self, notice: ProgramNotice) -> Self:
        """
        Return a line notices with the added notice
        """

    def replace(
        self, chooser: ProgramNoticeChooser, *, replaced: ProgramNotice, first_only: bool = True
    ) -> Self:
        """
        Return a copy where the chosen notice(s) are replaced

        Only replace first notice that is found if first_only is True
        """

    def remove(self, chooser: ProgramNoticeChooser) -> Self:
        """
        Return a copy where chosen notices aren't included
        """


class FileNotices(Protocol):
    """
    Represents the information returned by the static type checker for a specific file
    """

    @property
    def location(self) -> pathlib.Path:
        """
        The path to this file as represented by the type checker
        """

    @property
    def has_notices(self) -> bool:
        """
        Whether this file has notices
        """

    def __iter__(self) -> Iterator[ProgramNotice]:
        """
        Yield all the notices
        """

    def notices_for_line_number(self, line_number: int) -> LineNotices | None:
        """
        Return the line notices for a specific line number if there are any
        """

    @overload
    def find_for_name_or_line(
        self, *, name_or_line: str | int, severity: str | None = None, must_exist: Literal[True]
    ) -> tuple[int, LineNotices, ProgramNotice]: ...

    @overload
    def find_for_name_or_line(
        self,
        *,
        name_or_line: str | int,
        severity: str | None = None,
        must_exist: Literal[False] = False,
    ) -> tuple[int, LineNotices, ProgramNotice | None]: ...
    def find_for_name_or_line(
        self, *, name_or_line: str | int, severity: str | None = None, must_exist: bool = False
    ) -> tuple[int, LineNotices, ProgramNotice | None]:
        """
        Return the line_number, notices at that line, and the matched notice
        """

    def set_name(self, name: str, line_number: int) -> Self:
        """
        Associate a name with a specific line number
        """

    def set_line_notices(self, line_number: int, notices: LineNotices) -> Self:
        """
        Return a modified notices with these notices for the specified line number
        """

    def add_notice(self, line_number: int, notice: ProgramNotice) -> Self:
        """
        Return a modified notices with this additional notice
        """

    def add_reveal(self, *, name_or_line: str | int, revealed: str) -> Self:
        """
        Return a modified notices with this additional reveal note
        """

    def change_reveal(self, *, name_or_line: str | int, modify: ProgramNoticeModify) -> Self:
        """
        Return a modified notices with a changed reveal notice at this named line
        """

    def add_error(self, *, name_or_line: str | int, error_type: str, error: str) -> Self:
        """
        Return a modified notices with this additional error notice
        """

    def change_error(self, *, name_or_line: str | int, modify: ProgramNoticeModify) -> Self:
        """
        Return a modified notices with a changed error notice at this named line
        """

    def add_note(self, *, name_or_line: str | int, note: str) -> Self:
        """
        Return a modified notices with this additional note
        """

    def change_note(self, *, name_or_line: str | int, modify: ProgramNoticeModify) -> Self:
        """
        Return a modified notices with a changed note at this named line
        """

    def remove_notices(self, *, name_or_line: str | int, chooser: ProgramNoticeChooser) -> Self:
        """
        Return a copy where the chosen notices at specified line are removed
        """


class FileNoticesChanger(Protocol):
    """
    Used to make some changes to the FileNotices
    """

    def __call__(self, notices: FileNotices) -> FileNotices: ...


class FileNoticesParser(Protocol):
    """
    Used to parse notices from comments in a file
    """

    def __call__(self, location: pathlib.Path) -> FileNotices: ...


class ProgramNotices(Protocol):
    """
    Represents the information returned by the static type check
    """

    @property
    def has_notices(self) -> bool:
        """
        Whether there were any notices
        """

    def __iter__(self) -> Iterator[ProgramNotice]:
        """
        Yield all the notices
        """

    def diff(self, root_dir: pathlib.Path, other: ProgramNotices) -> DiffNotices:
        """
        Return an object representing what is the same and what is different between two program notices
        """


class Expectations(Protocol[T_Scenario]):
    """
    This objects knows what to expect from running the static type checker
    """

    def check_results(self, result: RunResult[T_Scenario]) -> None:
        """
        Used to check the result against these expectations
        """


class ExpectationsMaker(Protocol[T_Scenario]):
    """
    Callable that creates an Expectations object
    """

    def __call__(
        self,
        scenario_runner: ScenarioRunner[T_Scenario],
        options: RunOptions[T_Scenario],
    ) -> Expectations[T_Scenario]: ...


class Scenario(Protocol):
    """
    Used to hold relevant information for running and testing a type checker run.

    This object is overridden to provide a mechanism for stringing custom data throughout
    all the other objects.

    A default implementation is provided by ``pytest_typing_runner.Scenario``

    The ``typing_scenario_maker`` fixture can be defined to return the exact concrete
    implementation to use for a particular scope.
    """

    same_process: bool
    typing_strategy: Strategy
    root_dir: pathlib.Path
    check_paths: list[str]
    expect_fail: bool
    expect_dmypy_restarted: bool

    def execute_static_checking(
        self: T_Scenario, file_modification: FileModifier, options: RunOptions[T_Scenario]
    ) -> RunResult[T_Scenario]:
        """
        Called to use the run options to run a type checker and get a result
        """

    def parse_notices_from_file(self, location: pathlib.Path) -> FileNotices:
        """
        Used to find comments in a file that represent expected notices
        """

    def check_results(
        self: T_Scenario, result: RunResult[T_Scenario], expectations: Expectations[T_Scenario]
    ) -> None:
        """
        Called to check the result against expectations
        """


class ScenarioRunner(Protocol[T_Scenario]):
    """
    Used to facilitate the running and testing of a type checker run.

    A default implementation is provided by ``pytest_typing_runner.ScenarioRunner``

    The ``typing_`` fixture can be defined to return the exact concrete
    implementation to use for a particular scope.
    """

    @property
    def scenario(self) -> T_Scenario:
        """
        The scenario under test
        """

    def run_and_check(self, make_expectations: ExpectationsMaker[T_Scenario]) -> None:
        """
        Used to do a run of a type checker and check against the provided expectations
        """

    @property
    def runs(self) -> ScenarioRuns[T_Scenario]:
        """
        The runs of the type checker for this scenario
        """

    def prepare_scenario(self) -> None:
        """
        Called when the scenario has been created. This method may do any mutations it
        wants on self.scenario
        """

    def cleanup_scenario(self) -> None:
        """
        Called after the test is complete. This method may do anything it wants for cleanup
        """

    def add_to_pytest_report(self, name: str, sections: list[tuple[str, str]]) -> None:
        """
        Used to add a section to the pytest report
        """

    def determine_options(self) -> RunOptions[T_Scenario]:
        """
        Called to determine what to run the type checker with
        """

    def file_modification(self, path: str, content: str | None) -> None:
        """
        Used to modify a file for the scenario and record it on the runs
        """


class ScenarioMaker(Protocol[T_CO_Scenario]):
    """
    Represents a callable that creates Scenario objects
    """

    def __call__(self, *, config: RunnerConfig, root_dir: pathlib.Path) -> T_CO_Scenario: ...


class ScenarioRunnerMaker(Protocol[T_Scenario]):
    """
    Represents an object that creates Scenario Runner objects
    """

    def __call__(
        self,
        *,
        config: RunnerConfig,
        root_dir: pathlib.Path,
        scenario_maker: ScenarioMaker[T_Scenario],
    ) -> ScenarioRunner[T_Scenario]: ...


class ScenarioFile(Protocol):
    """
    Used to hold information about a file in a scenario
    """

    @property
    def root_dir(self) -> pathlib.Path:
        """
        The root dir of the scenario
        """

    @property
    def path(self) -> str:
        """
        The path to this file relative to the rootdir
        """

    def notices(self) -> FileNotices:
        """
        Return the notices associated with this file
        """


class ScenarioFileMaker(Protocol[T_CO_ScenarioFile]):
    """
    Callable that returns a ScenarioFile
    """

    def __call__(self, *, root_dir: pathlib.Path, path: str) -> T_CO_ScenarioFile: ...


if TYPE_CHECKING:
    P_Scenario = Scenario

    P_ScenarioFile = ScenarioFile
    P_ScenarioRun = ScenarioRun[P_Scenario]
    P_ScenarioRuns = ScenarioRuns[P_Scenario]
    P_Expectations = Expectations[P_Scenario]
    P_ScenarioMaker = ScenarioMaker[P_Scenario]
    P_ScenarioRunner = ScenarioRunner[P_Scenario]
    P_ScenarioFileMaker = ScenarioFileMaker[P_ScenarioFile]
    P_ExpectationsMaker = ExpectationsMaker[P_Scenario]
    P_ScenarioRunnerMaker = ScenarioRunnerMaker[P_Scenario]

    P_FileNotices = FileNotices
    P_LineNotices = LineNotices
    P_ProgramNotice = ProgramNotice
    P_ProgramNotices = ProgramNotices
    P_FileNoticesChanger = FileNoticesChanger
    P_FileNoticesParser = FileNoticesParser
    P_DiffNotices = DiffNotices
    P_DiffFileNotices = DiffFileNotices

    P_FileModifier = FileModifier
    P_RunOptions = RunOptions[P_Scenario]
    P_RunResult = RunResult[P_Scenario]
    P_RunnerConfig = RunnerConfig
    P_ProgramRunner = ProgramRunner[P_Scenario]

    _FM: P_FileModifier = cast(P_ScenarioRunner, None).file_modification
