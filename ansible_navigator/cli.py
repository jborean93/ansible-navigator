""" start here
"""
import json
import logging
import os
import sys
import sysconfig
import signal
import time

from argparse import Namespace
from curses import wrapper
from functools import partial
from typing import Callable
from typing import List
from typing import Optional
from typing import Tuple

from .cli_args import CliArgs
from .config import APP_NAME, NavigatorConfig
from .action_runner import ActionRunner

from .utils import check_for_ansible
from .utils import error_and_exit_early
from .utils import flatten_list
from .utils import set_ansible_envar
from .utils import Sentinel

logger = logging.getLogger(APP_NAME)


def setup_logger(logfile: str, log_level: str):
    """set up the logger

    """
    if os.path.exists(logfile):
        with open(logfile, "w"):
            pass
    hdlr = logging.FileHandler(logfile)
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)s '%(name)s.%(funcName)s' %(message)s",
        datefmt="%y%m%d%H%M%S",
    )
    formatter.converter = time.gmtime
    hdlr.setFormatter(formatter)
    logger.addHandler(hdlr)
    logger.setLevel(getattr(logging, loglevel.upper()))


def parse_and_update(params: List, error_cb: Callable = None) -> Namespace:
    """parse some params and update the config"""
    parser = CliArgs(APP_NAME).parser

    if error_cb:
        parser.error = error_cb  # type: ignore
    args, cmdline = parser.parse_known_args(params)

    NavigatorConfig().load_argparse_results(args)

    return args


def run(args: Namespace) -> None:
    """run the appropriate app"""
    try:
        mode = _CONFIG.get('mode')
        if args.app in ["run", "config", "inventory"] and mode == "stdout":
            try:
                app_action = __import__(
                    f"actions.{args.app}", globals(), fromlist=["Action"], level=1
                )
            except ImportError as exc:
                msg = (
                    f"either action '{args.app}' is invalid or does not support"
                    f" mode '{mode}'. Failed with error {exc}"
                )
                logger.error(msg)
                error_and_exit_early(str(msg))

            non_ui_app = partial(app_action.Action(args).run_stdout)
            non_ui_app()
        else:
            wrapper(ActionRunner(args=args).run)
    except KeyboardInterrupt:
        logger.warning("Dirty exit, killing the pid")
        os.kill(os.getpid(), signal.SIGTERM)


class

def main():
    """start here"""
    # TODO: Find a better way of using the logger. Maybe it shouldn't be tied to the cli and just follows python norms
    pre_logger_msgs = []
    config = NavigatorConfig(pre_logger_msgs)

    # pylint: disable=too-many-branches
    try:
        args = parse_and_update(sys.argv[1:])
    except ValueError as e:
        error_and_exit_early(str(e))

    setup_logger(config.get('log-file'), config.get('log-level'))
    for msg in pre_logger_msgs:
        logger.debug(msg)

    # post process inventory
    if args.app == "inventory" and not _CONFIG.get('inventory', None):
        error_and_exit_early("an inventory is required when using the inventory explorer")

    # post process load
    if args.app == "load" and not os.path.exists(args.value):
        error_and_exit_early(f"The file specified with load could not be found. {args.load}")

    # post process welcome
    if not args.app:
        _CONFIG.set('mode', 'interactive')
        args.app = "welcome"
        args.value = None

    share_dir = _CONFIG.get('share-dir', None)
    if not share_dir:
        error_and_exit_early("problem finding share dir")

    pre_logger_msgs += msgs

    args.original_command = params

    for key, value in sorted(vars(args).items()):
        pre_logger_msgs.append(f"Running with {key} as {value} {type(value)}")

    os.environ.setdefault("ESCDELAY", "25")
    os.system("clear")

    if not hasattr(args, "requires_ansible") or args.requires_ansible:
        if not _CONFIG.get('execution-environment'):
            success, msg = check_for_ansible()
            if success:
                logger.debug(msg)
            else:
                logger.critical(msg)
                error_and_exit_early(msg)
        set_ansible_envar()

    run(args)


if __name__ == "__main__":
    main()
