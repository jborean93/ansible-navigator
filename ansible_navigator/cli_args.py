""" Build the args
https://www.gnu.org/software/libc/manual/html_node/Argument-Syntax.html
"""
from argparse import ArgumentParser

from .config import NavigatorConfig, argparse_path


class CliArgs:
    """Build the args"""

    # pylint: disable=too-few-public-methods
    def __init__(self, app_name: str):
        self._navigator_config = NavigatorConfig()

        self._app_name = app_name
        self._base_parser = ArgumentParser(add_help=False)
        self._base()
        self.parser = ArgumentParser(
            parents=[self._base_parser]
        )
        self._subparsers = self.parser.add_subparsers(
            title="subcommands",
            description="valid subcommands",
            help="additional help",
            dest="app",
            metavar="{command} --help",
        )
        self._collections()
        self._config()
        self._doc()
        self._inventory()
        self._load()
        self._run()

    def _add_subparser(self, name: str, desc: str) -> ArgumentParser:
        return self._subparsers.add_parser(
            name,
            help=desc,
            description=f"{name}: {desc}",
            parents=[self._base_parser],
        )

    def _base(self) -> None:
        self._editor_params(self._base_parser)
        self._ee_params(self._base_parser)
        self._inventory_columns(self._base_parser)
        self._log_params(self._base_parser)
        self._no_osc4_params(self._base_parser)
        self._mode(self._base_parser)

    def _collections(self) -> None:
        parser = self._add_subparser("collections", "Explore installed collections")
        parser.set_defaults(requires_ansible=True)

    def _config(self) -> None:
        self._add_subparser("config", "Explore the current ansible configuration")

    def _doc(self) -> None:
        parser = self._add_subparser("doc", "Show a plugin doc")
        self._doc_params(parser)

    def _doc_params(self, parser: ArgumentParser) -> None:
        parser.add_argument("value", metavar="plugin", help="The name of the plugin", type=str)

        self._add_argument(parser, 'doc-plugin-type')
        parser.set_defaults(requires_ansible=True)

    def _editor_params(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'editor-command')
        self._add_argument(parser, 'editor-console')

    def _ee_params(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'container-engine')
        self._add_argument(parser, 'execution-environment')
        self._add_argument(parser, 'execution-environment-image')
        self._add_argument(parser, 'set-environment-variable')
        self._add_argument(parser, 'pass-environment-variable')

    def _run(self) -> None:
        parser = self._add_subparser(
            "run", "Run Ansible playbook in either interactive or stdout mode"
        )
        self._playbook_params(parser)
        self._inventory_params(parser)

    def _inventory_columns(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'inventory-columns')

    def _inventory(self) -> None:
        parser = self._add_subparser("inventory", "Explore inventories")
        self._inventory_params(parser)

    def _inventory_params(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'inventory')

    def _load(self) -> None:
        parser = self._add_subparser("load", "Load an artifact")
        self._load_params(parser)

    @staticmethod
    def _load_params(parser: ArgumentParser) -> None:
        parser.add_argument(
            "value",
            default=None,
            help="The file name of the artifact",
            metavar="artifact",
            type=argparse_path,
        )
        parser.set_defaults(requires_ansible=False)

    def _log_params(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'log-file')
        self._add_argument(parser, 'log-level')

    def _no_osc4_params(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'no-osc4')

    def _playbook_params(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'playbook')
        self._add_argument(parser, 'playbook-artifact')
        parser.set_defaults(requires_ansible=True)

    def _mode(self, parser: ArgumentParser) -> None:
        self._add_argument(parser, 'mode')

    def _add_argument(self, parser: ArgumentParser, name: str) -> None:
        args, kwargs = self._navigator_config.get_argparse_info(name)
        parser.add_argument(*args, **kwargs)
