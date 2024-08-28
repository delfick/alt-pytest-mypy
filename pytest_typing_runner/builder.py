import dataclasses
import functools
import pathlib
from collections.abc import Callable, MutableMapping
from typing import TYPE_CHECKING, Generic, cast

from typing_extensions import Self, TypeVar

from . import expectations, file_changer, notices, protocols

T_CO_ScenarioFile = TypeVar(
    "T_CO_ScenarioFile", bound="ScenarioFile", default="ScenarioFile", covariant=True
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ScenarioFile:
    """
    Convenience object for working with a file in the scenario

    Implements :protocol:`pytest_typing_runner.protocols.ScenarioFile`

    :param path: Path to the file relative to ``root_dir``
    :param root_dir: Path the files for the scenario can be made in
    :param file_parser: Used to parse and transform content for notice expectations
    :param file_modification: used to change files and record those changes
    """

    path: str
    root_dir: pathlib.Path
    file_parser: protocols.FileNoticesParser
    file_modification: protocols.FileModifier

    _overrides: list[protocols.FileNoticesChanger] = dataclasses.field(
        init=False, default_factory=list
    )

    _file_parser_override: dict[None, protocols.FileNoticesParser] = dataclasses.field(
        init=False, default_factory=dict
    )

    def set(self, content: str | None) -> Self:
        """
        Used to override the content for this file

        :param content: The content to put in this file
        :returns: This scenario file instance
        """
        parser = self.file_parser
        if None in self._file_parser_override:
            parser = self._file_parser_override[None]

        if content is not None:
            content, _ = parser(
                content, into=notices.FileNotices(location=self.root_dir / self.path)
            )

        self.file_modification(path=self.path, content=content)
        return self

    def append(self, content: str, *, divider: str = "\n", must_exist: bool = True) -> Self:
        """
        Used to append content to a file

        :param content:
            The content to add to the end of the file. If ``must_exist`` is False
            and the file doesn't already exist then the file is created with only
            this content.
        :param divider: String to put before the content if there is existing content
        :param must_exist: raise an error if the file does not already exist
        :returns: This scenario file instance
        """
        return self.set(
            content=file_changer.FileAppender(
                root_dir=self.root_dir, path=self.path, extra_content=content
            ).after_append(divider=divider, must_exist=must_exist),
        )

    def expect(self, *instructions: protocols.FileNoticesChanger) -> Self:
        """
        Add changes to the notices we expect from this file after the type checker
        runs.

        :params instructions:
            Instructions to store. When the final expectations are being built
            these are used on the file notices for this file to change what
            notices are expected for this file
        :returns: This scenario file instance
        """
        for instruction in instructions:
            self._overrides.append(instruction)
        return self

    def override_file_parser(self, parser: protocols.FileNoticesParser | None) -> Self:
        """
        Change the file parser used for this file.

        :param parser: The new parser to use.
        :returns: This scenario file instance
        """
        if parser is None:
            self._file_parser_override.clear()
        else:
            self._file_parser_override[None] = parser
        return self

    def notices(self, *, into: protocols.FileNotices) -> protocols.FileNotices | None:
        """
        Used to determine what notices are expected for this file.

        Determined by using the parser on the contents of the file and then
        running the resulting file notices through all the overrides provided
        by the ``expect`` method.

        :param into: A file notices object to use as the base for holding the notices
        :raises AssertionError: if the parser wants to change the content of the file
        :returns: The final file notices object
        """
        parser = self.file_parser
        file_notices = into
        if None in self._file_parser_override:
            parser = self._file_parser_override[None]

        location = self.root_dir / self.path
        original = location.read_text()
        replacement, file_notices = parser(original, into=file_notices)
        assert (
            replacement == original
        ), f"Contents of '{self.path}' were not transformed when written to disk"

        for instruction in self._overrides:
            changed = instruction(file_notices)
            if changed is None:
                file_notices = into.clear(clear_names=True)
            else:
                file_notices = changed

        if not file_notices.has_notices:
            return None

        return file_notices


@dataclasses.dataclass(frozen=True, kw_only=True)
class ScenarioBuilder(Generic[protocols.T_Scenario, T_CO_ScenarioFile]):
    '''
    A convenience object for managing files and expectations in a scenario.

    .. code-block:: python

        import functools

        import pytest
        from pytest_typing_runner import builder, parse, protocols


        class Builder(builder.ScenarioBuilder[protocols.Scenario, builder.ScenarioFile]):
            pass


        @pytest.fixture
        def build(typing_scenario_runner: protocols.ScenarioRunner[protocols.Scenario]) -> Builder:
            return Builder(
                scenario_runner=typing_scenario_runner,
                scenario_file_maker=functools.partial(
                    builder.ScenarioFile,
                    file_parser=parse.FileContent().parse,
                    file_modification=typing_scenario_runner.file_modification,
                ),
            )


        def test_things(build: Builder) -> None:
            @build.run_and_check_after
            def _() -> None:
                build.on("main.py").set(
                    """
                    a: int = 1
                    # ^ REVEAL ^ builtins.int
                    """
                )

            @build.run_and_check_after
            def _() -> None:
                build.expect_failure()
                build.on("main.py").append(
                    """
                    a = "asdf"
                    # ^ ERROR(assignment) ^ Incompatible types in assignment (expression has type "str", variable has type "int")
                    """
                )

    :param scenario_file_maker: Used to make a scenario file object for each file
    :param scenario_runner: The ScenarioRunner for that Scenario
    '''

    scenario_file_maker: protocols.ScenarioFileMaker[T_CO_ScenarioFile]
    scenario_runner: protocols.ScenarioRunner[protocols.T_Scenario]

    _known_files: MutableMapping[str, T_CO_ScenarioFile] = dataclasses.field(
        init=False, default_factory=dict
    )

    def on(self, path: str) -> T_CO_ScenarioFile:
        """
        Create, store and remember ScenarioFile objects for specific paths

        :param path: path to the file we want to change
        :returns: The ScenarioFile object for this path
        """
        if path not in self._known_files:
            self._known_files[path] = self.scenario_file_maker(
                path=path, root_dir=self.scenario_runner.scenario.root_dir
            )
        return self._known_files[path]

    def run_and_check(
        self,
        *,
        _change_expectations: Callable[[], None] | None = None,
    ) -> None:
        """
        Call run_and_check on the scenario_runner with expectations created
        by the builder
        """

        def setup_expectations(
            *, options: protocols.RunOptions[protocols.T_Scenario]
        ) -> protocols.ExpectationsMaker[protocols.T_Scenario]:
            if _change_expectations is not None:
                _change_expectations()

            return functools.partial(self.make_expectations, options=options)

        return self.scenario_runner.run_and_check(setup_expectations)

    def run_and_check_after(self, action: Callable[[], None]) -> None:
        """
        Decorator to run some function before using run_and_check

        .. code-block::

            @builder.run_and_check_after
            def _() -> None:
                # change builder here
                # to create files and expectations
                # before the type checker is run

        :param action: The function to call to setup the scenario
        """
        self.run_and_check(_change_expectations=action)

    def make_expectations(
        self, *, options: protocols.RunOptions[protocols.T_Scenario]
    ) -> protocols.Expectations[protocols.T_Scenario]:
        """
        Used to generate the expectations the builder is aware of

        :param options: The options for running the type checker
        :returns: The expectations for the run
        """
        root_dir = options.cwd
        program_notices = options.scenario_runner.generate_program_notices()

        return expectations.Expectations(
            expect_fail=self.scenario_runner.scenario.expects.failure,
            expect_stderr="",
            expect_notices=program_notices.set_files(
                {
                    (location := root_dir / path): known.notices(
                        into=program_notices.generate_notices_for_location(location)
                    )
                    for path, known in self._known_files.items()
                }
            ),
        )

    def expect_failure(self) -> Self:
        """
        Record on the builder that future builds are expected to fail
        """
        self.scenario_runner.scenario.expects.failure = True
        return self

    def expect_success(self) -> Self:
        """
        Record on the builder that future builds are expected to succeed
        """
        self.scenario_runner.scenario.expects.failure = False
        return self

    def daemon_should_not_restart(self) -> Self:
        """
        Record on the builder that future builds are expected to not result
        in the daemon restarting if the program runner uses a daemon.
        """
        self.scenario_runner.scenario.expects.daemon_restarted = False
        return self

    def daemon_should_restart(self) -> Self:
        """
        Record on the builder that future builds are expected to result
        in the daemon restarting if the program runner uses a daemon.
        """
        self.scenario_runner.scenario.expects.daemon_restarted = True
        return self


if TYPE_CHECKING:
    _SC: protocols.P_ScenarioFile = cast(ScenarioFile, None)

    _SCM: protocols.P_ScenarioFileMaker = functools.partial(
        ScenarioFile,
        file_parser=cast(protocols.FileNoticesParser, None),
        file_modification=cast(protocols.FileModifier, None),
    )
