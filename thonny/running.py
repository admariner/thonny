# -*- coding: utf-8 -*-

"""Code for maintaining the background process and for running
user programs

Commands get executed via shell, this way the command line in the
shell becomes kind of title for the execution.

"""
import collections
import os.path
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import warnings
from abc import ABC, abstractmethod
from logging import getLogger
from threading import Thread
from time import sleep
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple, Union  # @UnusedImport; @UnusedImport

import thonny
from thonny import (
    common,
    get_runner,
    get_shell,
    get_thonny_user_dir,
    get_vendored_libs_dir,
    get_version,
    get_workbench,
    report_time,
)
from thonny.common import (
    ALL_EXPLAINED_STATUS_CODE,
    PROCESS_ACK,
    BackendEvent,
    CommandToBackend,
    DebuggerCommand,
    DebuggerResponse,
    DistInfo,
    EOFCommand,
    InlineCommand,
    InlineResponse,
    InputSubmission,
    MessageFromBackend,
    ToplevelCommand,
    ToplevelResponse,
    UserError,
    is_same_path,
    parse_message,
    path_startswith,
    read_one_incoming_message_str,
    serialize_message,
    try_get_base_executable,
    universal_relpath,
    update_system_path,
)
from thonny.editors import (
    get_current_breakpoints,
    get_saved_current_script_path,
    get_target_dir_from_uri,
)
from thonny.languages import tr
from thonny.misc_utils import (
    UNTITLED_URI_SCHEME,
    construct_cmd_line,
    inside_flatpak,
    is_local_uri,
    is_remote_uri,
    running_on_mac_os,
    running_on_windows,
    show_command_not_available_in_flatpak_message,
    uri_to_target_path,
)
from thonny.ui_utils import select_sequence, show_dialog
from thonny.workdlg import WorkDialog

logger = getLogger(__name__)

WINDOWS_EXE = "python.exe"
OUTPUT_MERGE_THRESHOLD = 1000

RUN_COMMAND_LABEL = ""  # init later when gettext is ready
RUN_COMMAND_CAPTION = ""
EDITOR_CONTENT_TOKEN = "$EDITOR_CONTENT"

INTERRUPT_SEQUENCE = "<Control-c>"

CSI_TERMINATOR = re.compile("[@-~]")
OSC_TERMINATOR = re.compile(r"\a|\x1B\\")

TERMINATION_TIMEOUT = 2
TERMINATION_POLL_INTERVAL = 0.02

# other components may turn it on in order to avoid grouping output lines into one event
io_animation_required = False

_console_allocated = False

BASE_MODULES = [
    "_abc",
    "_codecs",
    "_collections_abc",
    "_distutils_hack",
    "_frozen_importlib",
    "_frozen_importlib_external",
    "_imp",
    "_io",
    "_signal",
    "_sitebuiltins",
    "_stat",
    "_thread",
    "_warnings",
    "_weakref",
    "_winapi",
    "abc",
    "builtins",
    "codecs",
    "encodings",
    "genericpath",
    "io",
    "marshal",
    "nt",
    "ntpath",
    "os",
    "site",
    "stat",
    "sys",
    "time",
    "winreg",
    "zipimport",
]


class Runner:
    def __init__(self) -> None:
        get_workbench().set_default("run.allow_running_unnamed_programs", True)
        get_workbench().set_default("run.auto_cd", True)
        get_workbench().set_default("run.warn_module_shadowing", True)

        self._init_commands()
        self._state = "starting"
        self._proxy: Optional[BackendProxy] = None
        self._publishing_events = False
        self._polling_after_id = None
        self._postponed_commands = []  # type: List[CommandToBackend]
        self._thread_commands = queue.Queue()
        self._thread_command_results = {}
        self._running_thread_command_ids = set()
        self._last_accepted_backend_command = None

    def start(self) -> None:
        global _console_allocated
        try:
            self._check_alloc_console()
            _console_allocated = True
        except Exception:
            logger.exception("Problem allocating console")
            _console_allocated = False

        try:
            self.restart_backend(False, True)
        except Exception as e:
            logger.exception("Could not start backend when starting Runner")
            get_shell().print_error(f"\nStarting the back-end failed with following error: {e}\n")

    def _init_commands(self) -> None:
        global RUN_COMMAND_CAPTION, RUN_COMMAND_LABEL

        RUN_COMMAND_LABEL = tr("Run current script")
        RUN_COMMAND_CAPTION = tr("Run")

        get_workbench().set_default("run.run_in_terminal_python_repl", False)
        get_workbench().set_default("run.run_in_terminal_keep_open", True)

        try:
            import thonny.plugins.debugger  # @UnusedImport

            debugger_available = True
        except ImportError:
            debugger_available = False

        get_workbench().add_command(
            "run_current_script",
            "run",
            RUN_COMMAND_LABEL,
            caption=RUN_COMMAND_CAPTION,
            handler=self.cmd_run_current_script,
            default_sequence="<F5>",
            extra_sequences=[select_sequence("<Control-r>", "<Command-r>")],
            tester=self.cmd_run_current_script_enabled,
            group=10,
            image="run-current-script",
            include_in_toolbar=not (get_workbench().in_simple_mode() and debugger_available),
            show_extra_sequences=True,
        )

        get_workbench().add_command(
            "run_current_script_in_terminal",
            "run",
            tr("Run current script in terminal"),
            caption="RunT",
            handler=self._cmd_run_current_script_in_terminal,
            default_sequence="<Control-t>",
            extra_sequences=["<<CtrlTInText>>"],
            tester=self._cmd_run_current_script_in_terminal_enabled,
            group=35,
            image="terminal",
        )

        get_workbench().add_command(
            "restart",
            "run",
            tr("Stop/Restart backend"),
            caption=tr("Stop"),
            handler=self.cmd_stop_restart,
            default_sequence="<Control-F2>",
            group=100,
            image="stop",
            include_in_toolbar=True,
        )

        get_workbench().add_command(
            "interrupt",
            "run",
            tr("Interrupt execution"),
            handler=self._cmd_interrupt,
            tester=self._cmd_interrupt_enabled,
            default_sequence=INTERRUPT_SEQUENCE,
            skip_sequence_binding=True,  # Sequence will be bound differently
            group=100,
            bell_when_denied=False,
        )
        get_workbench().bind(INTERRUPT_SEQUENCE, self._cmd_interrupt_with_shortcut, True)

        get_workbench().add_command(
            "ctrld",
            "run",
            tr("Send EOF / Soft reboot"),
            self.ctrld,
            self.ctrld_enabled,
            group=100,
            default_sequence="<Control-d>",
            extra_sequences=["<<CtrlDInText>>"],
        )

        get_workbench().add_command(
            "disconnect",
            "run",
            tr("Disconnect"),
            self.disconnect,
            self.disconnect_enabled,
            group=100,
        )

    def get_state(self) -> str:
        """State is one of "running", "waiting_debugger_command", "waiting_toplevel_command" """
        return self._state

    def _set_state(self, state: str) -> None:
        if self._state != state:
            logger.debug("Runner state changed: %s ==> %s" % (self._state, state))
            self._state = state

    def is_running(self):
        return self._state == "running"

    def is_waiting(self):
        return self._state.startswith("waiting")

    def is_waiting_toplevel_command(self):
        return self._state == "waiting_toplevel_command"

    def is_waiting_debugger_command(self):
        return self._state == "waiting_debugger_command"

    def get_sys_path(self) -> List[str]:
        return self._proxy.get_sys_path()

    def send_command(self, cmd: CommandToBackend) -> None:
        logger.info("Runner.send_command %r", cmd)
        self._send_initial_or_queued_command(cmd)

    def _send_initial_or_queued_command(self, cmd: CommandToBackend) -> None:
        if self._proxy is None:
            return

        if self._publishing_events:
            # allow all event handlers to complete before sending the commands
            # issued by first event handlers
            self._postpone_command(cmd, "there are events to be published")
            return

        # First sanity check
        if (
            isinstance(cmd, ToplevelCommand)
            and not self.is_waiting_toplevel_command()
            and cmd.name not in ["Reset", "Run", "Debug"]
            or isinstance(cmd, DebuggerCommand)
            and not self.is_waiting_debugger_command()
        ):
            get_workbench().bell()
            logger.warning("RUNNER: Command %s was attempted at state %s" % (cmd, self.get_state()))
            return

        # Attach extra info
        if "debug" in cmd.name.lower():
            cmd["breakpoints"] = get_current_breakpoints()

        if "id" not in cmd:
            cmd["id"] = generate_command_id()

        cmd["local_cwd"] = get_workbench().get_local_cwd()

        if self._proxy.running_inline_command and isinstance(cmd, InlineCommand):
            reason = "running another inline command"
            cur_cmd_name = getattr(self._last_accepted_backend_command, "name", None)
            if cur_cmd_name:
                reason += f" ({cur_cmd_name})"
            self._postpone_command(cmd, reason)
            return

        # Offer the command
        logger.debug("Runner: sending command %r to proxy: %s", cmd.name, cmd)
        try:
            response = self._proxy.send_command(cmd)
        except Exception as e:
            logger.exception("proxy raised exception for command")
            get_shell().print_error(f"\nCommand {cmd.name} failed with following error: {e}\n")
            return None
        logger.debug("send_command response from proxy: %r", response)

        if response == "discard":
            logger.info("back-end discarded the command")
            return None
        elif response == "postpone":
            self._postpone_command(cmd, "back-end requested postpone")
            return
        else:
            assert response is None
            get_workbench().event_generate("CommandAccepted", command=cmd)
            self._last_accepted_backend_command = cmd
            if isinstance(cmd, InlineCommand):
                self._proxy.running_inline_command = True

        if isinstance(cmd, (ToplevelCommand, DebuggerCommand)):
            self._set_state("running")

        if cmd.name[0].isupper():
            # This may be only logical restart, which does not look like restart to the runner
            get_workbench().event_generate("BackendRestart", full=False)

    def send_command_and_wait(self, cmd: InlineCommand, dialog_title: str) -> MessageFromBackend:
        dlg = InlineCommandDialog(get_workbench(), cmd, title=dialog_title + " ...")
        show_dialog(dlg)
        return dlg.response

    def send_command_and_wait_in_thread(
        self, cmd: InlineCommand, timeout: int
    ) -> MessageFromBackend:
        logger.info("Runner.send_command_and_wait_in_thread %r", cmd)
        # should not send directly, as we're in thread
        cmd_id = cmd.get("id")
        if cmd_id is None:
            cmd_id = generate_command_id()
            cmd["id"] = cmd_id

        start_time = time.time()
        proxy_at_start = self._proxy

        self._thread_commands.put(cmd)

        while time.time() - start_time < timeout:
            if self._proxy is not proxy_at_start:
                raise RuntimeError("Backend restarted")
            elif cmd_id in self._thread_command_results:
                result = self._thread_command_results[cmd_id]
                del self._thread_command_results[cmd_id]
                return result
            else:
                time.sleep(0.1)
        else:
            raise TimeoutError(f"Could not receive response to {cmd} in {timeout} seconds")

    def _postpone_command(self, cmd: CommandToBackend, reason: str) -> None:
        logger.info("Postponing command. Reason: %s", reason)

        # in case of InlineCommands, discard older same type command
        if isinstance(cmd, InlineCommand):
            for older_cmd in self._postponed_commands:
                if older_cmd.name == cmd.name:
                    logger.info("Discarding older command of same type")
                    self._postponed_commands.remove(older_cmd)

        if len(self._postponed_commands) > 10:
            logger.warning("Can't pile up too many commands. This command will be just ignored")
        else:
            self._postponed_commands.append(cmd)

    def _send_postponed_commands(self) -> None:
        todo = self._postponed_commands
        self._postponed_commands = []

        for cmd in todo:
            logger.info("Sending postponed command: %s", cmd)
            self._send_initial_or_queued_command(cmd)

    def _send_thread_commands(self) -> None:
        while not self._thread_commands.empty():
            cmd = self._thread_commands.get()
            self._running_thread_command_ids.add(cmd["id"])
            logger.info("Sending thread command: %s", cmd)
            self._send_initial_or_queued_command(cmd)

    def send_program_input(self, data: str) -> None:
        assert self.is_running()
        self._proxy.send_program_input(data)

    def execute_via_shell(
        self,
        cmd_line: Union[str, List[str]],
        working_directory: Optional[str] = None,
    ) -> None:
        if working_directory and self._proxy.get_cwd() != working_directory:
            # create compound command
            # start with %cd
            cd_cmd_line = construct_cd_command(working_directory) + "\n"
        else:
            # create simple command
            cd_cmd_line = ""

        if not isinstance(cmd_line, str):
            cmd_line = construct_cmd_line(cmd_line)

        # submit to shell (shell will execute it)
        get_shell().submit_magic_command(cd_cmd_line + cmd_line)

    def execute_script(
        self,
        script_path: str,
        args: List[str],
        working_directory: Optional[str],
        command_name: str = "Run",
    ) -> None:
        rel_filename = universal_relpath(script_path, working_directory)
        cmd_parts = ["%" + command_name, rel_filename] + args
        cmd_line = construct_cmd_line(cmd_parts, [EDITOR_CONTENT_TOKEN])

        self.execute_via_shell(cmd_line, working_directory)

    def execute_editor_content(self, command_name, args):
        if command_name.lower() in ["debug", "fastdebug"]:
            messagebox.showinfo(
                tr("Information"),
                tr("For debugging the program must be saved first."),
                master=get_workbench(),
            )
            return

        get_shell().submit_magic_command(
            construct_cmd_line(
                ["%" + command_name, "-c", EDITOR_CONTENT_TOKEN] + args, [EDITOR_CONTENT_TOKEN]
            )
        )

    def execute_current(self, command_name: str) -> None:
        """
        This method's job is to create a command for running/debugging
        current file/script and submit it to shell
        """

        if not self._proxy:
            return

        assert (
            command_name[0].isupper()
            or command_name == "run"
            and not self._proxy.should_restart_interpreter_before_run()
        )

        if not self.is_waiting_toplevel_command():
            logger.info("Trying to execute current but runner is %r", self.get_state())
            self._proxy.interrupt()

            try:
                self._wait_for_prompt(1)
            except TimeoutError:
                # turtle.mainloop, for example, is not easy to interrupt.
                get_shell().print_error("Could not interrupt current process. ")
                wait_instructions = "Please wait, try again or select Stop/Restart!"

                if self._proxy.stop_restart_kills_user_program():
                    get_shell().print_error("Forcing the program to stop.\n")
                    self.cmd_stop_restart()
                    try:
                        self._wait_for_prompt(1)
                    except TimeoutError:
                        get_shell().print_error(
                            "Could not force-stop the program. " + wait_instructions + "\n"
                        )
                else:
                    # For some back-ends (e.g. BareMetalMicroPython) killing is not an option.
                    # Besides, they may be configured to avoid refreshing the environment
                    # before run (for performance reasons).
                    get_shell().print_error(wait_instructions + "\n")
                    return

        editor = get_workbench().get_editor_notebook().get_current_editor()
        if not editor:
            return

        UNTITLED = f"{UNTITLED_URI_SCHEME}:0"
        if not editor.is_untitled() or not get_workbench().get_option(
            "run.allow_running_unnamed_programs"
        ):
            if not editor.is_untitled() and not editor.is_modified():
                # Don't attempt to save as the file may be read-only
                logger.debug("Not saving read only file %s", editor.get_uri())
                uri = editor.get_uri()
            else:
                uri = editor.save_file()
                if not uri:
                    # user has cancelled file saving
                    return
        else:
            uri = UNTITLED

        if not self._proxy:
            # Saving the file may have killed the proxy
            return

        if (
            is_remote_uri(uri)
            and not self._proxy.can_run_remote_files()
            or is_local_uri(uri)
            and not self._proxy.can_run_local_files()
            or uri == UNTITLED
        ):
            self.execute_editor_content(command_name, self._get_active_arguments())
        else:
            if get_workbench().get_option("run.auto_cd") and command_name[0].isupper():
                working_directory = get_target_dir_from_uri(uri)
            else:
                working_directory = self._proxy.get_cwd()

            target_path = uri_to_target_path(uri)
            self.execute_script(
                target_path, self._get_active_arguments(), working_directory, command_name
            )

    def _wait_for_prompt(self, timeout) -> None:
        start_time = time.time()
        while time.time() - start_time <= timeout:
            if self.is_waiting_toplevel_command():
                return
            get_workbench().update()
            sleep(0.01)

        raise TimeoutError("Backend did not respond in time")

    def _get_active_arguments(self):
        if get_workbench().get_option("view.show_program_arguments"):
            args_str = get_workbench().get_option("run.program_arguments")
            get_workbench().log_program_arguments_string(args_str)
            return shlex.split(args_str)
        else:
            return []

    def cmd_run_current_script_enabled(self) -> bool:
        return (
            self._proxy and get_workbench().get_editor_notebook().get_current_editor() is not None
        )

    def _cmd_run_current_script_in_terminal_enabled(self) -> bool:
        return (
            self._proxy
            and self._proxy.can_run_in_terminal()
            and self.cmd_run_current_script_enabled()
        )

    def cmd_run_current_script(self) -> None:
        if get_workbench().in_simple_mode():
            get_workbench().hide_view("VariablesView")
        report_time("Before Run")
        if self._proxy and self._proxy.should_restart_interpreter_before_run():
            self.execute_current("Run")
        else:
            self.execute_current("run")
        report_time("After Run")

    def _cmd_run_current_script_in_terminal(self) -> None:
        if inside_flatpak():
            show_command_not_available_in_flatpak_message()
            return

        path = get_saved_current_script_path()
        if not path:
            return

        self._proxy.run_script_in_terminal(
            path,
            self._get_active_arguments(),
            get_workbench().get_option("run.run_in_terminal_python_repl"),
            get_workbench().get_option("run.run_in_terminal_keep_open"),
        )

    def _cmd_interrupt(self) -> None:
        if self._proxy is not None:
            if _console_allocated:
                self._proxy.interrupt()
            else:
                messagebox.showerror(
                    "No console",
                    "Can't interrupt as console was not allocated.\n\nUse Stop/Restart instead.",
                    master=self,
                )
        else:
            logger.warning("User tried interrupting without proxy")

    def _cmd_interrupt_with_shortcut(self, event=None):
        if not self._cmd_interrupt_enabled():
            return None

        if not running_on_mac_os():  # on Mac Ctrl+C is not used for Copy.
            # Disable Ctrl+C interrupt in editor and shell, when some text is selected
            # (assuming user intended to copy instead of interrupting)
            widget = get_workbench().focus_get()
            if isinstance(widget, tk.Text):
                if len(widget.tag_ranges("sel")) > 0:
                    # this test is reliable, unlike selection_get below
                    return None
            elif isinstance(widget, (tk.Listbox, ttk.Entry, tk.Entry, tk.Spinbox)):
                try:
                    # NB! On Linux, selection_get() gives X selection
                    # i.e. it may be from another application when Thonny has nothing selected
                    selection = widget.selection_get()
                    if isinstance(selection, str) and len(selection) > 0:
                        # Assuming user meant to copy, not interrupt
                        # (IDLE seems to follow same logic)

                        # NB! This is not perfect, as in Linux the selection can be in another app
                        # ie. there may be no selection in Thonny actually.
                        # In other words, Ctrl+C interrupt may be dropped without reason
                        # when given inside the widgets listed above.
                        return None
                except Exception:
                    # widget either doesn't have selection_get or it
                    # gave error (can happen without selection on Ubuntu)
                    pass

        self._cmd_interrupt()
        return "break"

    def _cmd_interrupt_enabled(self) -> bool:
        return self._proxy and self._proxy.is_connected()

    def cmd_stop_restart(self) -> None:
        if get_workbench().in_simple_mode():
            get_workbench().hide_view("VariablesView")

        self.restart_backend(clean=True)

    def disconnect(self):
        proxy = self.get_backend_proxy()
        assert hasattr(proxy, "disconnect")
        proxy.disconnect()

    def disconnect_enabled(self):
        proxy = self.get_backend_proxy()
        return proxy is not None and proxy.needs_disconnect_button()

    def ctrld(self):
        proxy = self.get_backend_proxy()
        if not proxy:
            return

        if get_shell().has_pending_input():
            messagebox.showerror(
                "Can't perform this action",
                "Ctrl+D only has effect on an empty line / prompt.\n"
                + "Submit current input (press ENTER) and try again",
                master=get_workbench(),
            )
            return

        proxy.send_command(EOFCommand())
        self._set_state("running")

    def ctrld_enabled(self):
        proxy = self.get_backend_proxy()
        return proxy and proxy.is_connected()

    def _poll_backend_messages(self) -> None:
        """I chose polling instead of event_generate in listener thread,
        because event_generate across threads is not reliable
        http://www.thecodingforums.com/threads/more-on-tk-event_generate-and-threads.359615/
        """
        self._polling_after_id = None
        if self._pull_backend_messages() is False:
            return

        if self._proxy.has_next_message():
            # Some events didn't fit into this batch. Start the next batch as soon as possible
            self._polling_after_id = get_workbench().after_idle(self._poll_backend_messages)
        else:
            # take it easy
            self._polling_after_id = get_workbench().after(
                20, lambda: get_workbench().after_idle(self._poll_backend_messages)
            )

    def _pull_backend_messages(self):
        # Don't process too many messages in single batch, allow screen updates
        # and user actions between batches.
        # Mostly relevant when backend prints a lot quickly.
        # TODO: Should I leave new messages (caused by processing this batch) for next batch?
        msg_count = 0
        max_msg_count = 10
        while self._proxy is not None and msg_count < max_msg_count:
            try:
                msg = self._proxy.fetch_next_message()
                if not msg:
                    break
                logger.debug("RUNNER GOT: %s in state: %s", msg.event_type, self.get_state())

                msg_count += 1
            except BackendTerminatedError as exc:
                logger.info("Backend terminated with code: %r", exc.returncode)
                self._handle_backend_termination(exc.returncode)
                return False

            # change state
            if isinstance(msg, ToplevelResponse):
                self._set_state("waiting_toplevel_command")
            elif isinstance(msg, DebuggerResponse):
                self._set_state("waiting_debugger_command")
            elif isinstance(msg, InlineResponse):
                # next inline command won't be sent before response from the last has arrived
                self._proxy.running_inline_command = False
            else:
                "other messages don't affect the state"

            command_id = msg.get("command_id")
            if command_id in self._running_thread_command_ids:
                self._running_thread_command_ids.remove(command_id)
                self._thread_command_results[command_id] = msg
            else:
                # Publish the event
                # NB! This may cause another command to be sent before we get to postponed commands
                try:
                    self._publishing_events = True
                    class_event_type = type(msg).__name__
                    get_workbench().event_generate(
                        class_event_type, event=msg
                    )  # more general event
                    if msg.event_type != class_event_type:
                        # more specific event
                        get_workbench().event_generate(msg.event_type, event=msg)
                finally:
                    self._publishing_events = False

            # TODO: is it necessary???
            # https://stackoverflow.com/a/13520271/261181
            # get_workbench().update()

        self._send_thread_commands()
        self._send_postponed_commands()

    def _handle_backend_termination(self, returncode: Optional[int]) -> None:
        if returncode is None or returncode == ALL_EXPLAINED_STATUS_CODE:
            err = ""
        else:
            err = f"Process ended with exit code {returncode}."

        try:
            faults_file = os.path.join(get_thonny_user_dir(), "backend_faults.log")
            if os.path.exists(faults_file):
                with open(faults_file, encoding="ASCII", errors="replace") as fp:
                    err += fp.read()
        except Exception:
            logger.exception("Failed retrieving backend faults")

        get_workbench().event_generate("ProgramOutput", stream_name="stderr", data="\n" + err)

        get_workbench().become_active_window(False)
        self.destroy_backend()
        if self._should_restart_after_command(self._last_accepted_backend_command):
            self.restart_backend(clean=True, automatic=True)

    def _should_restart_after_command(self, cmd: CommandToBackend):
        if cmd is None or not hasattr(cmd, "name"):
            return False

        return cmd.name in ["Run", "run", "Debug", "debug", "execute_source"]

    def restart_backend(self, clean: bool, first: bool = False, automatic: bool = False) -> None:
        """Recreate (or replace) backend proxy / backend process."""
        logger.info(
            "Restarting back-end, clean: %r, first: %r, automatic: %r", clean, first, automatic
        )
        was_running = self.is_running()
        self.destroy_backend()
        self._last_accepted_backend_command = None
        backend_name = get_workbench().get_option("run.backend_name")
        if backend_name not in get_workbench().get_backends():
            raise UserError(
                f"Unknown interpreter kind '{backend_name}'. Please select another interpreter from options"
            )

        backend_class = get_workbench().get_backends()[backend_name].proxy_class
        self._set_state("running")
        self._proxy = None
        logger.info("Starting backend %r", backend_class)
        self._proxy = backend_class(clean)

        if not first:
            get_shell().restart(automatic=automatic, was_running=was_running)
            get_shell().update_idletasks()

        get_workbench().event_generate("BackendRestart", full=True)

        get_workbench().after_idle(self._poll_backend_messages)

    def destroy_backend(self, for_restart: bool = False) -> None:
        logger.info("Destroying backend")

        if self._polling_after_id is not None:
            get_workbench().after_cancel(self._polling_after_id)
            self._polling_after_id = None

        self._postponed_commands = []
        if self._proxy:
            self._proxy.destroy(for_restart=for_restart)
            self._proxy = None
            get_workbench().event_generate("BackendTerminated")

    def get_backend_proxy(self) -> "BackendProxy":
        return self._proxy

    def _check_alloc_console(self) -> None:
        if sys.executable.endswith("pythonw.exe"):
            # These don't have console allocated.
            # Console is required for sending interrupts.

            # AllocConsole would be easier but flashes console window

            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            exe = sys.executable.replace("pythonw.exe", "python.exe")

            cmd = [exe, "-c", "print('Hi!'); input()"]
            child = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
            )
            child.stdout.readline()
            result = kernel32.AttachConsole(child.pid)
            if not result:
                err = ctypes.get_last_error()
                logger.info("Could not allocate console. Error code: " + str(err))
            child.stdin.write(b"\n")
            try:
                child.stdin.flush()
            except Exception:
                # May happen eg. when installation path has "&" in it
                # See https://bitbucket.org/plas/thonny/issues/508/cant-allocate-windows-console-when
                # Without flush the console window becomes visible, but Thonny can be still used
                logger.exception("Problem with finalizing console allocation")

    def ready_for_remote_file_operations(self, show_message=False):
        if not self._proxy or not self.supports_remote_files():
            return False

        ready = self._proxy.ready_for_remote_file_operations()

        if not ready and show_message:
            if not self._proxy.is_connected():
                msg = "Device is not connected"
            else:
                msg = (
                    "Device is busy -- can't perform this action now."
                    + "\nPlease wait or cancel current work and try again!"
                )
            messagebox.showerror(tr("Can't complete"), msg, master=get_workbench())

        return ready

    def supports_remote_files(self):
        if self._proxy is None:
            return False
        else:
            return self._proxy.supports_remote_files()

    def supports_remote_directories(self):
        if self._proxy is None:
            return False
        else:
            return self._proxy.supports_remote_directories()

    def get_node_label(self):
        if self._proxy is None:
            return "Back-end"
        else:
            return self._proxy.get_node_label()

    def using_venv(self) -> bool:
        from thonny.plugins.cpython_frontend import LocalCPythonProxy
        from thonny.plugins.cpython_ssh.cps_front import SshCPythonProxy

        return (
            isinstance(self._proxy, (LocalCPythonProxy, SshCPythonProxy)) and self._proxy._in_venv
        )

    def is_connected(self):
        if self._proxy is None:
            return False
        else:
            return self._proxy.is_connected()


class BackendProxy(ABC):
    """Communicates with backend process.

    All communication methods must be non-blocking,
    ie. suitable for calling from GUI thread."""

    # backend_name will be overwritten on Workbench.add_backend
    # Subclasses don't need to worry about it.
    backend_name = None
    backend_description = None

    def __init__(self, clean: bool) -> None:
        """Initializes (or starts the initialization of) the backend process.

        Backend is considered ready when the runner gets a ToplevelResponse
        with attribute "welcome_text" from fetch_next_message.
        """
        self.running_inline_command = False

    @abstractmethod
    def send_command(self, cmd: CommandToBackend) -> Optional[str]:
        """Send the command to backend. Return None, 'discard' or 'postpone'"""

    @abstractmethod
    def send_program_input(self, data: str) -> None:
        """Send input data to backend"""

    @abstractmethod
    def has_next_message(self) -> bool: ...

    @abstractmethod
    def fetch_next_message(self):
        """Read next message from the queue or None if queue is empty"""

    @abstractmethod
    def get_sys_path(self):
        "backend's sys.path"
        ...

    @abstractmethod
    def get_board_id(self): ...

    def get_backend_name(self):
        return type(self).backend_name

    @abstractmethod
    def interrupt(self):
        """Tries to interrupt current command without resetting the backend"""
        ...

    @abstractmethod
    def destroy(self, for_restart: bool = False):
        """Called when Thonny no longer needs this instance
        (Thonny gets closed or new backend gets selected)
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Returns True if the backend is operational.
        Returns False if the connection is lost (or not created yet)
        or the remote process has died (or not created yet).
        """
        ...

    def disconnect(self):
        """
        Means different things for different backends.
        For local CPython it does nothing (???).
        For BareMetalMicroPython it means simply closing the serial connection.
        For SSH back-ends it means closing the SSH connection.
        """
        pass

    def needs_disconnect_button(self):
        return False

    @abstractmethod
    def has_local_interpreter(self): ...

    @abstractmethod
    def interpreter_is_cpython_compatible(self) -> bool: ...

    @abstractmethod
    def get_target_executable(self) -> Optional[str]:
        """Returns `sys.executable` if the interpreter has it."""

    def get_node_label(self):
        """Used as files caption if back-end has separate files,
        also when choosing file save target"""
        return "Back-end"

    def get_full_label(self):
        return self.get_node_label()

    def supports_remote_files(self):
        """Whether remote file browser should be presented with this back-end"""
        return False

    def uses_local_filesystem(self):
        """Whether it runs code from local files"""
        return True

    def should_restart_interpreter_before_run(self) -> bool:
        return True

    def stop_restart_kills_user_program(self) -> bool:
        return True

    def supports_remote_directories(self):
        return False

    def supports_trash(self):
        return True

    def can_run_remote_files(self):
        raise NotImplementedError()

    def can_run_local_files(self):
        raise NotImplementedError()

    @abstractmethod
    def can_debug(self) -> bool: ...

    def ready_for_remote_file_operations(self):
        return False

    def get_cwd(self) -> Optional[str]:
        return None

    @abstractmethod
    def get_current_switcher_configuration(self) -> Dict[str, Any]:
        """returns the dict of configuration entries that distinguish current backend conf from other
        items in the backend switcher. Also used for collecting last used configurations."""

    @classmethod
    @abstractmethod
    def get_switcher_configuration_label(cls, conf: Dict[str, Any]) -> str:
        """Formats configuration for menu item"""

    @classmethod
    @abstractmethod
    def get_switcher_entries(cls) -> List[Tuple[Dict[str, Any], str, str]]:
        """
        Each returned entry creates one item in the backend switcher menu.
        """

    @abstractmethod
    def can_run_in_terminal(self) -> bool: ...

    def run_script_in_terminal(self, script_path, args, interactive, keep_open):
        raise NotImplementedError()

    def has_custom_system_shell(self):
        return False

    def open_custom_system_shell(self) -> None:
        raise NotImplementedError()

    def get_package_installation_confirmations(self, dist_info: DistInfo) -> List[str]:
        if "thonny" in dist_info.name.lower():
            return [
                tr(
                    "Looks like you are installing a Thonny-related package.\n"
                    + "If you meant to install a Thonny plugin, then you should\n"
                    + "choose 'Tools → Manage plugins...' instead\n"
                    + "\n"
                    + "Are you sure you want to install %s for the back-end?"
                )
                % dist_info.name
            ]

        return []

    def supports_packages(self) -> bool:
        return True

    @abstractmethod
    def get_packages_target_dir_with_comment(self) -> Tuple[Optional[str], Optional[str]]:
        raise NotImplementedError()

    @abstractmethod
    def can_install_packages_from_files(self) -> bool:
        raise NotImplementedError()

    def get_externally_managed_message(self) -> str:
        return (
            tr("The packages of this interpreter can be managed via your system package manager.")
            + "\n"
            + tr("For pip-installing a package, you need to use a virtual environment.")
        )

    def normalize_target_path(self, path: str) -> str:
        return path

    @classmethod
    def search_packages(cls, query: str) -> List[DistInfo]:
        from thonny.plugins.pip_gui import perform_pypi_search

        return perform_pypi_search(
            query, get_workbench().get_data_url("pypi_summaries_cpython.json"), []
        )

    @classmethod
    def get_package_info_from_index(cls, name: str, version: str) -> DistInfo:
        from thonny.plugins.pip_gui import download_dist_info_from_pypi

        return download_dist_info_from_pypi(name, version)

    @classmethod
    def get_version_list_from_index(cls, name: str) -> List[str]:
        from thonny.plugins.pip_gui import try_download_version_list_from_pypi

        return try_download_version_list_from_pypi(name)

    def get_search_button_text(self) -> str:
        return tr("Search on PyPI")

    @classmethod
    def get_vendored_user_stubs_ids(cls) -> List[str]:
        return []

    @classmethod
    def get_user_stubs_location(cls) -> str:
        result_path = os.path.join(thonny.get_thonny_user_dir(), "stubs", cls.backend_name)
        if not os.path.exists(result_path):
            # copy default stubs to user editable location on the first request
            os.makedirs(result_path)
            for vendored_id in cls.get_vendored_user_stubs_ids():
                vendored_path = os.path.join(get_vendored_libs_dir(), vendored_id)
                for item_name in os.listdir(vendored_path):
                    full_item_path = os.path.join(vendored_path, item_name)
                    if os.path.isdir(full_item_path):
                        shutil.copytree(full_item_path, os.path.join(result_path, item_name))
                    else:
                        shutil.copy(full_item_path, os.path.join(result_path, item_name))
        return result_path

    def get_machine_id(self) -> str:
        return "localhost"


class SubprocessProxy(BackendProxy, ABC):
    def __init__(self, clean: bool) -> None:
        super().__init__(clean)

        self._mgmt_executable = self.compute_mgmt_executable()

        if ".." in self._mgmt_executable:
            self._mgmt_executable = os.path.normpath(self._mgmt_executable)

        self._welcome_text = ""

        self._proc = None
        self._response_queue = None
        self._sys_path = []
        self._board_id: Optional[str] = None
        self._usersitepackages = None
        self._externally_managed = None
        self._reported_executable = None
        self._gui_update_loop_id = None
        self._in_venv = None
        self._cwd = self._get_initial_cwd()  # pylint: disable=assignment-from-none
        self._start_background_process(clean=clean)
        self._have_check_remembered_current_configuration = False

    def compute_mgmt_executable(self) -> str:
        return get_front_interpreter_for_subprocess()

    def _check_remember_current_configuration(self) -> None:
        current_configuration = self.get_current_switcher_configuration()
        if not self._should_remember_configuration(current_configuration):
            return

        last_configurations = self.get_last_configurations()
        if current_configuration in last_configurations:
            last_configurations.remove(current_configuration)

        last_configurations.insert(0, current_configuration)

        # remove non-valid
        last_configurations = [
            conf for conf in last_configurations if self.is_valid_configuration(conf)
        ]
        # Remember only last 5
        last_configurations = last_configurations[:5]
        self.set_last_configurations(last_configurations)

    def _should_remember_configuration(self, configuration: Dict[str, Any]) -> bool:
        return True

    @classmethod
    def get_last_configurations(cls) -> List[Dict]:
        return get_workbench().get_option(f"{cls.backend_name}.last_configurations")

    @classmethod
    def set_last_configurations(cls, value: List[Dict[str, Any]]) -> None:
        return get_workbench().set_option(f"{cls.backend_name}.last_configurations", value)

    @classmethod
    @abstractmethod
    def is_valid_configuration(cls, conf: Dict[str, Any]) -> bool:
        """Returns whether it makes sense to present this configuration in the switcher"""
        ...

    def _get_initial_cwd(self):
        return None

    def _get_environment(self):
        env = get_environment_for_python_subprocess(self._mgmt_executable)
        # variables controlling communication with the back-end process
        env["PYTHONIOENCODING"] = "utf-8"

        # because cmd line option -u won't reach child processes
        # see https://github.com/thonny/thonny/issues/808
        env["PYTHONUNBUFFERED"] = "1"

        env["PYTHONSAFEPATH"] = "1"

        # Let back-end know about plug-ins
        env["THONNY_USER_DIR"] = get_thonny_user_dir()
        env["THONNY_FRONTEND_SYS_PATH"] = repr(sys.path)

        env["THONNY_LANGUAGE"] = get_workbench().get_option("general.language")
        env["THONNY_VERSION"] = get_version()

        if thonny.in_debug_mode():
            env["THONNY_DEBUG"] = "1"
        elif "THONNY_DEBUG" in env:
            del env["THONNY_DEBUG"]
        return env

    def get_mgmt_executable_special_switches(self) -> List[str]:
        return []

    def get_mgmt_executable_python_switches(self) -> List[str]:
        return [
            "-u",  # unbuffered IO
            "-B",  # don't write pyo/pyc files
            # (to avoid problems when using different Python versions without write permissions)
        ]

    def _start_background_process(self, clean=None, extra_args=[]):
        # deque, because in one occasion I need to put messages back
        logger.info("Starting background process, clean: %r, extra_args: %r", clean, extra_args)
        self._response_queue = collections.deque()

        exe_validation_error = self.get_mgmt_executable_validation_error()
        if exe_validation_error:
            raise RuntimeError(exe_validation_error)

        cmd_line = (
            [self._mgmt_executable]
            + self.get_mgmt_executable_special_switches()
            + self.get_mgmt_executable_python_switches()
            + self._get_launcher_with_args()
            + extra_args
        )

        if self.can_be_isolated():
            cmd_line.insert(1, "-s")

        creationflags = 0
        if running_on_windows():
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

        logger.info("Starting the backend: %s %s", cmd_line, get_workbench().get_local_cwd())

        self._proc = subprocess.Popen(
            cmd_line,
            executable=cmd_line[0],
            bufsize=0,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._get_launch_cwd(),
            env=self._get_environment(),
            universal_newlines=True,
            creationflags=creationflags,
            encoding="utf-8",
        )

        # read success acknowledgement
        stdout_line = self._proc.stdout.readline().strip("\r\n")

        # only attempt initial input if process started nicely,
        # otherwise can't read the error from stderr
        if stdout_line == PROCESS_ACK:
            # setup asynchronous output listeners
            Thread(target=self._listen_stdout, args=(self._proc.stdout,), daemon=True).start()
            Thread(target=self._listen_stderr, args=(self._proc.stderr,), daemon=True).start()

            self._send_initial_input()
        else:

            return_code = self._proc.poll()
            if return_code is not None:
                err = self._proc.stderr.read()
                if err:
                    get_shell().print_error(err)

            raise RuntimeError(
                f"Could not start back-end process, got {stdout_line!r} instead of {PROCESS_ACK!r}"
            )

    def get_mgmt_executable_validation_error(self) -> Optional[str]:
        if not os.path.isfile(self._mgmt_executable):
            return f"INTERNAL ERROR: interpreter {self._mgmt_executable!r} not found."

    def _send_initial_input(self) -> None:
        # Used for sending data sending for startup, which can't be send by other means
        # (e.g. don't want the password to end up in logs)

        pass

    def _get_launch_cwd(self):
        return get_workbench().get_local_cwd()

    def _get_launcher_with_args(self):
        raise NotImplementedError()

    def send_command(self, cmd: CommandToBackend) -> Optional[str]:
        """Send the command to backend. Return None, 'discard' or 'postpone'"""
        if isinstance(cmd, ToplevelCommand) and cmd.name[0].isupper():
            self._prepare_clean_launch()
            logger.info("Prepared clean state for executing %r", cmd)

        if isinstance(cmd, ToplevelCommand):
            # required by SshCPythonBackend for creating fresh target process
            cmd["expected_cwd"] = self._cwd

        method_name = "_cmd_" + cmd.name

        if hasattr(self, method_name):
            getattr(self, method_name)(cmd)
        else:
            self._send_msg(cmd)

    def _send_msg(self, msg):
        if not self._proc:
            logger.warning("Ignoring command without active backend process")
            return

        try:
            self._proc.stdin.write(serialize_message(msg) + "\n")
            self._proc.stdin.flush()
        except BrokenPipeError:
            import traceback

            traceback.print_stack()
            logger.exception("Could not write message or flush")
            get_shell().print_error(f"Could not perform {type(msg).__name__}")

    def _prepare_clean_launch(self):
        pass

    def send_program_input(self, data):
        self._send_msg(InputSubmission(data))

    def process_is_alive(self):
        return self._proc is not None and self._proc.poll() is None

    def is_terminated(self):
        return not self.process_is_alive()

    def is_connected(self):
        return self.process_is_alive()

    def get_sys_path(self):
        return self._sys_path

    def get_board_id(self):
        return self._board_id

    def destroy(self, for_restart: bool = False):
        self._close_backend()

    def _close_backend(self):
        if self._proc is not None and self._proc.poll() is None:
            logger.info("Trying to terminate backend process")
            self._proc.terminate()
            # Wait a bit
            for i in range(int(TERMINATION_TIMEOUT / TERMINATION_POLL_INTERVAL)):
                time.sleep(TERMINATION_POLL_INTERVAL)
                if self._proc.poll() is not None:
                    logger.info("Terminated in %s seconds", (i + 1) * TERMINATION_POLL_INTERVAL)
                    break
            else:
                logger.info(
                    "Could terminate backend process in %s seconds. Will kill.", TERMINATION_TIMEOUT
                )
                self._proc.kill()

        self._proc = None
        self._response_queue = None

    def _listen_stdout(self, stdout):
        # will be called from separate thread

        # allow self._response_queue to be replaced while processing
        message_queue = self._response_queue

        def publish_as_msg(data):
            msg = parse_message(data)
            if "cwd" in msg:
                self.cwd = msg["cwd"]
            message_queue.append(msg)

            if len(message_queue) > 10:
                # Probably backend runs an infinite/long print loop.
                # Throttle message throughput in order to keep GUI thread responsive.
                while len(message_queue) > 0:
                    sleep(0.005)

        while True:
            try:
                data = read_one_incoming_message_str(stdout.readline)
            except IOError:
                # TODO: What's this ???
                sleep(0.1)
                continue

            # debug("... read some stdout data", repr(data))
            if data == "":
                logger.info("Reader got EOF")
                break
            else:
                try:
                    publish_as_msg(data)
                except Exception:
                    # Can mean the line was from subprocess,
                    # which can't be captured by stream faking.
                    # NB! If subprocess printed it without linebreak,
                    # then the suffix can be thonny message

                    parts = data.rsplit(common.MESSAGE_MARKER, maxsplit=1)

                    # print first part as it is
                    message_queue.append(
                        BackendEvent("ProgramOutput", data=parts[0], stream_name="stdout")
                    )

                    if len(parts) == 2:
                        second_part = common.MESSAGE_MARKER + parts[1]
                        try:
                            publish_as_msg(second_part)
                        except Exception:
                            # just print ...
                            message_queue.append(
                                BackendEvent(
                                    "ProgramOutput", data=second_part, stream_name="stdout"
                                )
                            )

    def _listen_stderr(self, stderr):
        while True:
            data = read_one_incoming_message_str(stderr.readline)
            if data == "":
                logger.info("Reached end of STDERR")
                break
            else:
                self._response_queue.append(
                    BackendEvent("ProgramOutput", stream_name="stderr", data=data)
                )
                logger.error("STDERR: %r", data)

    def _store_state_info(self, msg):
        if "cwd" in msg:
            self._cwd = msg["cwd"]
            self._publish_cwd(msg["cwd"])

        if msg.get("welcome_text"):
            self._welcome_text = msg["welcome_text"]

        if "in_venv" in msg:
            self._in_venv = msg["in_venv"]

        if "sys_path" in msg:
            self._sys_path = msg["sys_path"]

        if msg.get("board_id", None) is not None:
            logger.info("Got board_id: %r", msg["board_id"])
            if self._board_id != msg["board_id"]:
                self._board_id = msg["board_id"]
                did_change_stubs = self._check_set_board_specific_stubs(self._board_id)
                if did_change_stubs:
                    get_workbench().start_or_restart_language_servers()

        if "usersitepackages" in msg:
            self._usersitepackages = msg["usersitepackages"]

        if "externally_managed" in msg:
            self._externally_managed = msg["externally_managed"]

        if "prefix" in msg:
            self._sys_prefix = msg["prefix"]

        if "exe_dirs" in msg:
            self._exe_dirs = msg["exe_dirs"]

        if msg.get("executable"):
            self._reported_executable = msg["executable"]

        if msg.get("base_executable"):
            self._reported_base_executable = msg["base_executable"]

        if "logfile" in msg:
            logger.info("Back-end reported logfile: %s", msg["logfile"])

    def _check_set_board_specific_stubs(self, board_id: str) -> bool:
        user_stubs_location = self.get_user_stubs_location()
        if user_stubs_location is None:
            return False

        logger.debug("Trying to set up board specific stubs for %r", board_id)

        specific_board_path = os.path.join(
            user_stubs_location, "board_definitions", board_id, "__init__.pyi"
        )
        if not os.path.exists(specific_board_path):
            logger.debug("Board path %r does not exist", specific_board_path)
            return False

        # replace in both stdlib and in plain packages, as different language servers may use different precedences
        did_replace = False
        for target_path in [
            os.path.join(user_stubs_location, "board", "__init__.pyi"),
            os.path.join(user_stubs_location, "stdlib", "board", "__init__.pyi"),
        ]:

            if not os.path.exists(target_path):
                continue

            files_are_identical = True
            with open(specific_board_path, "br") as f1, open(target_path, "br") as f2:
                while True:
                    line1 = f1.readline()
                    line2 = f2.readline()
                    if line1 == b"" and line2 == b"":
                        break

                    if line1 != line2:
                        files_are_identical = False
                        break

            if not files_are_identical:
                logger.info("Copying %r over %r", specific_board_path, target_path)
                shutil.copy(specific_board_path, target_path)
                did_replace = True

        return did_replace

    def _publish_cwd(self, cwd):
        if self.uses_local_filesystem():
            get_workbench().set_local_cwd(cwd)

    def get_site_packages(self):
        # NB! site.sitepackages may not be present in virtualenv
        for d in self._sys_path:
            if d.endswith("site-packages") and path_startswith(d, self._sys_prefix):
                return d

        return None

    def get_user_site_packages(self):
        return self._usersitepackages

    def is_externally_managed(self):
        return self._externally_managed or False

    def get_cwd(self):
        return self._cwd

    def get_exe_dirs(self):
        return self._exe_dirs

    def can_be_isolated(self) -> bool:
        """Says whether the backend may be launched with -s switch"""
        return True

    def has_next_message(self) -> bool:
        if self.is_terminated():
            return False

        return len(self._response_queue) > 0

    def fetch_next_message(self):
        if not self._response_queue or len(self._response_queue) == 0:
            if self.is_terminated():
                raise BackendTerminatedError(self._proc.returncode if self._proc else None)
            else:
                return None

        msg = self._response_queue.popleft()
        if isinstance(msg, ToplevelResponse):
            self._store_state_info(msg)
            if not self._have_check_remembered_current_configuration:
                self._check_remember_current_configuration()
                self._have_check_remembered_current_configuration = True

        if msg.event_type == "ProgramOutput":
            # combine available small output messages to one single message,
            # in order to put less pressure on UI code

            wait_time = 0.01
            total_wait_time = 0
            while True:
                if len(self._response_queue) == 0:
                    if _ends_with_incomplete_ansi_code(msg["data"]) and total_wait_time < 0.1:
                        # Allow reader to send the remaining part
                        sleep(wait_time)
                        total_wait_time += wait_time
                        continue
                    else:
                        return msg
                else:
                    next_msg = self._response_queue.popleft()
                    if (
                        next_msg.event_type == "ProgramOutput"
                        and next_msg["stream_name"] == msg["stream_name"]
                        and (
                            len(msg["data"]) + len(next_msg["data"]) <= OUTPUT_MERGE_THRESHOLD
                            and ("\n" not in msg["data"] or not io_animation_required)
                            or _ends_with_incomplete_ansi_code(msg["data"])
                        )
                    ):
                        msg["data"] += next_msg["data"]
                    else:
                        # not to be sent in the same block, put it back
                        self._response_queue.appendleft(next_msg)
                        return msg

        else:
            return msg


def _ends_with_incomplete_ansi_code(data):
    pos = max(data.rfind("\033["), data.rfind("\033]"))

    if pos == -1:
        return False

    if len(data) < 3:
        return True

    # note CSI_TERMINATOR also includes [
    params_and_terminator = data[pos + 2 :]
    if data[1] == "[":
        return not CSI_TERMINATOR.search(params_and_terminator)
    elif data[1] == "]":
        return not OSC_TERMINATOR.search(params_and_terminator)


def create_frontend_python_process(
    args,
    stdin=None,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    environment_extras: Optional[Dict[str, str]] = None,
    universal_newlines: bool = True,
):
    """Used for running helper commands (eg. for installing plug-ins on by the plug-ins)"""
    if _console_allocated:
        python_exe = get_front_interpreter_for_subprocess().replace("pythonw.exe", "python.exe")
    else:
        python_exe = get_front_interpreter_for_subprocess().replace("python.exe", "pythonw.exe")
    env = get_environment_for_python_subprocess(python_exe)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if environment_extras is not None:
        env.update(environment_extras)
    return _create_python_process(
        python_exe, args, stdin, stdout, stderr, env=env, universal_newlines=universal_newlines
    )


def _create_python_process(
    python_exe,
    args,
    stdin=None,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    shell=False,
    env=None,
    universal_newlines=True,
):
    cmd = [python_exe] + args

    if running_on_windows():
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    else:
        startupinfo = None
        creationflags = 0

    proc = subprocess.Popen(
        cmd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        shell=shell,
        env=env,
        universal_newlines=universal_newlines,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )

    proc.cmd = cmd
    return proc


class BackendTerminatedError(Exception):
    def __init__(self, returncode=None):
        Exception.__init__(self)
        self.returncode = returncode


def is_venv_interpreter_of_current_interpreter(executable):
    return try_get_base_executable(executable) == sys.executable


def get_environment_for_python_subprocess(target_executable) -> Dict[str, str]:
    overrides = get_environment_overrides_for_python_subprocess(target_executable)
    return get_environment_with_overrides(overrides)


def get_environment_with_overrides(overrides):
    env = os.environ.copy()
    for key in overrides:
        if overrides[key] is None and key in env:
            del env[key]
        else:
            assert isinstance(overrides[key], str)
            if key.upper() == "PATH":
                update_system_path(env, overrides[key])
            else:
                env[key] = overrides[key]
    return env


def get_environment_overrides_for_python_subprocess(target_executable):
    """Take care of not confusing different interpreter
    with variables meant for frontend interpreter"""

    # At the moment I'm tweaking the environment only if current
    # exe is bundled for Thonny.
    # In remaining cases it is user's responsibility to avoid
    # calling Thonny with environment which may be confusing for
    # different Pythons called in a subprocess.

    this_executable = sys.executable.replace("pythonw.exe", "python.exe")
    target_executable = target_executable.replace("pythonw.exe", "python.exe")

    interpreter_specific_keys = [
        "TCL_LIBRARY",
        "TK_LIBRARY",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONNOUSERSITE",
        "PYTHONUSERBASE",
    ]

    result = {}

    if os.path.samefile(
        target_executable, this_executable
    ) or is_venv_interpreter_of_current_interpreter(target_executable):
        # bring out some important variables so that they can
        # be explicitly set in macOS Terminal
        # (If they are set then it's most likely because current exe is in Thonny bundle)
        for key in interpreter_specific_keys:
            if key in os.environ:
                result[key] = os.environ[key]

        # never pass some variables to different interpreter
        # (even if it's venv or symlink to current one)
        if not is_same_path(target_executable, this_executable):
            for key in ["PYTHONPATH", "PYTHONHOME", "PYTHONNOUSERSITE", "PYTHONUSERBASE"]:
                if key in os.environ:
                    result[key] = None
    else:
        # interpreters are not related
        # interpreter specific keys most likely would confuse other interpreter
        for key in interpreter_specific_keys:
            if key in os.environ:
                result[key] = None

    # some keys should be never passed
    for key in [
        "PYTHONSTARTUP",
        "PYTHONBREAKPOINT",
        "PYTHONDEBUG",
        "PYTHONNOUSERSITE",
        "PYTHONASYNCIODEBUG",
        "VIRTUAL_ENV",
    ]:
        if key in os.environ:
            result[key] = None

    # venv may not find (correct) Tk without assistance (eg. in Ubuntu)
    if is_venv_interpreter_of_current_interpreter(target_executable):
        try:
            if "TCL_LIBRARY" not in os.environ or "TK_LIBRARY" not in os.environ:
                result["TCL_LIBRARY"] = get_workbench().tk.exprstring("$tcl_library")
                result["TK_LIBRARY"] = get_workbench().tk.exprstring("$tk_library")
        except Exception:
            logger.exception("Can't compute Tcl/Tk library location")

    return result


def construct_cd_command(path) -> str:
    return construct_cmd_line(["%cd", path])


_command_id_counter = 0
_command_id_counter_lock = threading.Lock()


def generate_command_id():
    global _command_id_counter
    with _command_id_counter_lock:
        _command_id_counter += 1
        return "cmd_" + str(_command_id_counter)


class InlineCommandDialog(WorkDialog):
    def __init__(
        self,
        master,
        cmd: Union[InlineCommand, Callable],
        title,
        instructions=None,
        output_prelude=None,
        autostart=True,
    ):
        self.response = None
        self._title = title
        self._instructions = instructions
        if "id" not in cmd:
            cmd["id"] = generate_command_id()
        self._cmd = cmd
        self.returncode = None

        get_shell().set_ignore_program_output(True)

        get_workbench().bind("InlineResponse", self._on_response, True)
        get_workbench().bind("InlineProgress", self._on_progress, True)
        get_workbench().bind("ProgramOutput", self._on_output, True)
        get_workbench().bind("BackendTerminated", self._on_backend_terminated, True)

        super().__init__(master, autostart=autostart)

        if output_prelude:
            self.append_text(output_prelude)

    def get_title(self):
        return self._title

    def get_instructions(self) -> Optional[str]:
        return self._instructions or self._cmd.get("description", "Working...")

    def _on_response(self, response):
        if response.get("command_id") == getattr(self._cmd, "id"):
            logger.debug("Dialog got response: %s", response)
            self.response = response
            self.returncode = response.get("returncode", None)
            success = (
                not self.returncode and not response.get("error") and not response.get("errors")
            )
            if success:
                self.set_action_text("Done!")
            else:
                self.set_action_text("Error")
                if response.get("error"):
                    self.append_text("Error %s\n" % response["error"], stream_name="stderr")
                if response.get("errors"):
                    self.append_text("Errors %s\n" % response["errors"], stream_name="stderr")
                if self.returncode:
                    self.append_text(
                        "Process returned with code %s\n" % self.returncode, stream_name="stderr"
                    )

            self.report_done(success)

    def _on_backend_terminated(self, msg):
        self.set_action_text("Error!")
        self.response = dict(error="Backend terminated")
        self.report_done(False)

    def _on_progress(self, msg):
        if msg.get("command_id") != getattr(self._cmd, "id"):
            return

        if msg.get("value", None) is not None and msg.get("maximum", None) is not None:
            self.report_progress(msg["value"], msg["maximum"])
        if msg.get("description"):
            self.set_action_text(msg["description"])

    def _on_output(self, msg):
        stream_name = msg.get("stream_name", "stdout")
        self.append_text(msg["data"], stream_name)
        self.set_action_text_smart(msg["data"])

    def start_work(self):
        self.send_command_to_backend()

    def send_command_to_backend(self):
        if not isinstance(self._cmd, CommandToBackend):
            # it was a lazy definition
            try:
                self._cmd = self._cmd()
            except Exception as e:
                logger.error("Could not produce command for backend", self._cmd)
                self.set_action_text("Error!")
                self.append_text("Could not produce command for backend\n")
                self.append_text("".join(traceback.format_exc()) + "\n")
                self.report_done(False)
                return

        logger.debug("Starting command in dialog: %s", self._cmd)
        get_runner().send_command(self._cmd)

    def cancel_work(self):
        super(InlineCommandDialog, self).cancel_work()
        get_runner()._cmd_interrupt()

    def close(self):
        get_workbench().unbind("InlineResponse", self._on_response)
        get_workbench().unbind("InlineProgress", self._on_progress)
        super(InlineCommandDialog, self).close()
        get_shell().set_ignore_program_output(False)


def get_frontend_python():
    # TODO: deprecated (name can be misleading)
    warnings.warn("get_frontend_python is deprecated")
    return get_front_interpreter_for_subprocess(sys.executable)


def get_front_interpreter_for_subprocess(candidate=None):
    if candidate is None:
        candidate = sys.executable

    pythonw = candidate.replace("python.exe", "pythonw.exe")
    if not _console_allocated and os.path.exists(pythonw):
        return pythonw
    else:
        return candidate.replace("pythonw.exe", "python.exe")
