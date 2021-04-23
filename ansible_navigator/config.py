"""
Configuration subsystem for ansible-navigator
"""
import json
import logger
import os
import os.path
import pkgutil

from argparse import ArgumentParser, Namespace
from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import Union
from yaml.scanner import ScannerError

from .utils import (
    Sentinel,
    Singleton,
    env_var_is_file_path,
    flatten_list,
    get_and_check_collection_doc_cache,
    get_conf_path,
)
from .yaml import yaml, SafeLoader


APP_NAME = "ansible_navigator"
COLLECTION_DOC_CACHE_FNAME = "collection_doc_cache.db"


def generate_editor_command():
    """generate a command for EDITOR is env var is set"""
    if "EDITOR" in os.environ:
        command = "%s {filename}" % os.environ.get("EDITOR")
    else:
        command = "vi +{line_number} {filename}"
    return command


# Contains default values for config options that cannot be expressed in yaml
_DEFAULT_OVERRIDES = {
    'editor-command': generate_editor_command(),
}


def argparse_bool(value: Any) -> bool:
    try:
        return _to_value_bool(value)
    except ValueError as e:
        raise ArgumentParser(str(e)) from None


def argparse_path(value: Any) -> Union[str, bytes]:
    try:
        return _to_value_path(value)
    except ValueError as e:
        raise ArgumentParser(str(e)) from None


def _to_value_path(fpath: Union[str, bytes]) -> Union[str, bytes]:
    """don't overload the ap type"""
    return os.path.abspath(os.path.expanduser(os.path.expandvars(fpath)))


def _to_value_bool(value) -> bool:
    """convert some commonly used values
    to a boolean
    """
    if isinstance(value, bool):
        return value

    value_l = value.lower()
    if value_l in ("yes", "true", "t", "y", "1"):
        return True
    if value_l in ("no", "false", "f", "n", "0"):
        return False
    raise ValueError("Boolean value expected.")


def _to_config_list(value: Any) -> Optional[List[str]]:
    """convert a config def to a list of strings"""
    if value is None:
        return value

    if not isinstance(value, list):
        value = [str(value)]

    return [str(v) for v in value]


def _to_config_str(value: Any) -> str:
    """convert a config def to string like value"""
    if value is None:
        raise ValueError("required value is not set")

    if isinstance(value, list):
        value = '. '.join(value)

    if not isinstance(value, str):
        raise ValueError("value is not a string or list of strings")

    value = value.strip()
    if not value.endswith('.'):
        value += '.'

    return value


def _validate_config_dict(value: Any, mandatory: Set, optional: Set, found: List[str]):
    """validates a config dict definition and sets all missing optional keys with a default of None"""
    error_key = " -> ".join(found)
    if not isinstance(value, dict):
        raise ValueError(f"{error_key} def is not a dict")

    actual_keys = set(value.keys())

    missing_keys = mandatory.difference(actual_keys)
    if missing_keys:
        raise ValueError(f"{error_key} def missing mandatory keys: {', '.join(missing_keys)}")

    extra_keys = actual_keys.difference(mandatory.union(optional))
    if extra_keys:
        raise ValueError(f"{error_key} def has extra keys: {', '.join(extra_keys)}")

    missing_optional = optional.difference(actual_keys)
    for missing in missing_optional:
        value[missing] = None


def _get_navigator_config_path(pre_logger_msgs: List[str]) -> Tuple['NavigatorConfigSource', Optional[str]]:
    """gets the user defined config file path if available"""
    config_path = None
    # Check if the conf path is set via an env var
    cfg_env_var = "ANSIBLE_NAVIGATOR_CONFIG"
    env_config_path, msgs = env_var_is_file_path(cfg_env_var, "config")
    pre_logger_msgs += msg

    # Check well know locations
    found_config_path, msg = get_conf_path(
        "ansible-navigator", allowed_extensions=["yml", "yaml", "json"]
    )
    pre_logger_msgs += msg

    # Pick the envar set first, followed by found, followed by leave as none
    if env_config_path is not None:
        pre_logger_msgs.append(f"Using config file at {config_path} set by {cfg_env_var}")
        return NavigatorConfigSource.ENVIRONMENT, env_config_path

    elif found_config_path is not None:
        pre_logger_msgs.append(f"Using config file at {config_path} in search path")
        return NavigatorConfigSource.WELL_KNOWN_LOCATION, found_config_path

    else:
        pre_logger_msgs.append("No valid config file found, using all default values for configuration.")
        return NavigatorConfigSource.NOT_FOUND, None


def _get_cache_dir() -> str:
    """get the ansible-navigator cache directory"""
    cache_home = os.environ.get("XDG_CACHE_HOME", f"{os.path.expanduser('~')}/.cache")
    cache_dir = f"{cache_home}/{APP_NAME}"

    return cache_dir


def _get_share_dir() -> Optional[str]:
    """
    returns datadir (e.g. /usr/share/ansible_nagivator) to use for the
    ansible-launcher data files. First found wins.
    """

    # Development path
    # We want the share directory to resolve adjacent to the directory the code lives in
    # as that's the layout in the source.
    path = os.path.join(os.path.dirname(__file__), "..", "share", APP_NAME)
    if os.path.exists(path):
        return path

    # ~/.local/share/APP_NAME
    userbase = sysconfig.get_config_var("userbase")
    if userbase is not None:
        path = os.path.join(userbase, "share", APP_NAME)
        if os.path.exists(path):
            return path

    # /usr/share/APP_NAME  (or the venv equivalent)
    path = os.path.join(sys.prefix, "share", APP_NAME)
    if os.path.exists(path):
        return path

    # /usr/share/APP_NAME  (or what was specified as the datarootdir when python was built)
    datarootdir = sysconfig.get_config_var("datarootdir")
    if datarootdir is not None:
        path = os.path.join(datarootdir, APP_NAME)
        if os.path.exists(path):
            return path

    # /usr/local/share/APP_NAME
    prefix = sysconfig.get_config_var("prefix")
    if prefix is not None:
        path = os.path.join(prefix, "local", "share", APP_NAME)
        if os.path.exists(path):
            return path

    # No path found above
    return None


def _load_navigator_config(path: str) -> Dict:
    """loads the user defined config file"""
    config = {}
    if path is not None:
        with open(path.encode('utf-8'), "r") as config_fh:
            if path.endswith(".json"):
                try:
                    config = json.load(config_fh)
                except (TypeError, json.decoder.JSONDecodeError) as exe:
                    raise TypeError(f"Invalid JSON config found in file '{path}'. "
                                    f"Failed with '{exe!s}'") from exe
            else:
                try:
                    config = yaml.load(config_fh, Loader=SafeLoader)
                except ScannerError as exe:
                    raise TypeError(f"Invalid YAML config found in file '{path}'. "
                                    f"Failed with '{exe!s}'") from exe

    return config


def _load_config_defs() -> Dict[str, Any]:
    """loads the config definition file, validates and sets the same default values"""
    raw_data = pkgutil.get_data('ansible_navigator.data', 'config.yml')
    config = yaml.load(raw_data.decode('utf-8'), Loader=SafeLoader)

    if not isinstance(config, dict):
        raise ValueError("builtin config.yml is a properly formed config definition file")

    # TODO: Add deprecated and version_added
    mandatory_keys = {'description'}
    optional_keys = {'default', 'choices', 'type', 'elements', 'config', 'env', 'cli', 'cli_opts'}

    for key, value in config.items():
        _validate_config_dict(value, mandatory_keys, optional_keys, [key])

        # Set sane defaults for the root keys
        if value['type'] is None:
            value['type'] = 'str'

        if key in _DEFAULT_OVERRIDES:
            value['default'] = _DEFAULT_OVERRIDES[key]

        elif value['default'] is None:
            if value['type'] == 'list':
                value['default'] = []
            elif value['type'] == 'dict':
                value['default'] = {}
            else:
                value['default'] = Sentinel

        if value['config'] is None:
            value['config'] = []

        if value['env'] is None:
            value['env'] = []

        if value['cli'] is None:
            value['cli'] = []

        if value['cli_opts'] is None:
            value['cli_opts'] = {}

        # Convert description to a string
        try:
            value['description'] = _to_config_str(value['description'])
        except ValueError as e:
            raise ValueError(f"{key} -> description def is invalid: {e!s}") from None

        value['choices'] = _to_config_list(value['choices'])

        # Validate the type options are valid
        valid_types = ['bool', 'dict', 'list', 'path', 'str']
        if value['type'] not in valid_types:
            raise ValueError(f"{key} -> type def {value['type']!s} is invalid: "
                             f"expecting {', '.join(valid_types)}")

        if value['elements'] and value['elements'] not in valid_types:
            raise ValueError(f"{key} -> elements def {value['elements']!s} is invalid: "
                             f"expecting {', '.join(valid_types)}")
        if value['elements'] is not None and value['type'] != 'list':
            raise ValueError(f"{key} -> elements def cannot be set when type is not list")

        # Validate the config/env/cli defs
        config_value = value['config']
        if not isinstance(config_value, list):
            raise ValueError(f"{key} -> config def is not a list")
        for entry in config_value:
            _validate_config_dict(entry, {'section', 'name'}, set(), [key, 'config'])
            entry['name'] = _to_config_str(entry['name'])
            entry['section'] = _to_config_list(entry['section'])

        env_value = value['env']
        if not isinstance(env_value, list):
            raise ValueError(f"{key} -> env def is not a list")
        for entry in env_value:
            _validate_config_dict(entry, {'name'}, set(), [key, 'env'])
            entry['name'] = str(entry['name'])

        cli_value = value['cli']
        if not isinstance(cli_value, list):
            raise ValueError(f"{key} -> cli def is not a list")
        for entry in cli_value:
            _validate_config_dict(entry, {'name'}, set(), [key, 'cli'])
            entry['name'] = str(entry['name'])

        _validate_config_dict(value['cli_opts'], set(), {'nargs'}, [key, 'cli_opts'])
        # Used by argparse to store the arguments to the property with this value
        value['cli_opts']['dest'] = key.lower().replace('-', '_')

    return config


class NavigatorConfigSource(Enum):
    """defines the config path source"""
    NOT_FOUND = "no config file found"
    ENVIRONMENT = "ANSIBLE_NAVIGATOR_CONFIG environment value"
    WELL_KNOWN_LOCATION = "well known folder location"


class NavigatorOptionSource(Enum):
    """defines the config option value source"""
    NOT_FOUND = "value was not defined in any option"
    DEFAULT = "default configuration value"
    USER_CFG = "user provided configuration file"
    ENVIRONMENT = "user provided environment variable"
    CLI = "user provided cli argument"
    EXPLICIT = "explicit value set by ansible-navigator"


class _ConfigValue:

    def __init__(self, name: str, definition: Dict[str, Any], config: Dict):
        self.name = name
        self._type = definition['type']
        self._elements = definition['elements']
        self._config_def = definition['config']
        self._env_def = definition['env']
        self._cli_def = definition['cli']

        self._values = {}
        self.set_value(definition['default'], NavigatorOptionSource.DEFAULT)

        for config_def in self._config_def:
            keys = config_def['section']
            keys.append(config_def['name'])

            current_val = config
            for k in keys:
                if not isinstance(current_val, dict):
                    # TODO: Add warning once logging is in place
                    break

                if k not in current_val:
                    current_val = Sentinel
                    break

                current_val = current_val[k]

            if current_val != Sentinel:
                self.set_value(NavigatorOptionSource.USER_CFG, current_val)

        all_env = os.environ
        for env_def in self._env_def:
            if env_def['name'] in all_env:
                self.set_value(NavigatorOptionSource.ENVIRONMENT, os.environ[env_def['name']])
                break

    def get_value(self, sources: List[NavigatorOptionSource]) -> Tuple[NavigatorOptionSource, Any]:
        for source in sources:
            if source in self._values:
                return source, self._values[source]

        else:
            return NavigatorOptionSource.NOT_FOUND, Sentinel

    def set_value(self, value: Any, source: NavigatorOptionSource):
        self._values[source] = self._cast_value(value, self._type, self._elements)

    def _cast_value(self, value: Any, value_type: str, elements: Optional[str] = None):
        # TODO: Improve these castings/validation
        if value_type == 'bool':
            return _to_value_bool(value)

        elif value_type == 'path':
            return _to_value_path(value)

        elif value_type == 'str':
            return str(value)

        elif value_type == 'list':
            if not isinstance(value, list):
                value = [value]

            return [self._cast_value(v, elements) for v in value]

        return value


class NavigatorConfig(metaclass=Singleton):
    """
    Global Navigator config that reads config values from the config file, environment, and cli arguments.
    """

    def __init__(self, pre_logger_msgs=None):
        # Used by cli.py as we cannot use the global logger without knowing the config/cli settings.
        pre_logger_msgs = pre_logger_msgs or []

        self._config_source, self._config_path = _get_navigator_config_path(pre_logger_msgs)
        self._config = _load_navigator_config(self._config_path) if self._config_path else {}

        self._def = _load_config_defs()
        self._values: Dict[str, _ConfigValue] = {n: _ConfigValue(n, v, self._config) for n, v in self._def.items()}

        # Set some internal values
        cache_dir = _get_cache_dir()
        share_dir = _get_share_dir()

        self.set('cache-dir', cache_dir)
        self.set('share-dir', share_dir)

        msgs, doc_cache = get_and_check_collection_doc_cache(
            cache_dir, share_dir, COLLECTION_DOC_CACHE_FNAME
        )
        self.set('collection-doc-cache', doc_cache)
        pre_logger_msgs += msgs

    def get(self, name: str, default: Any = Sentinel,
            sources: Optional[List[NavigatorOptionSource]] = None) -> Any:
        """
        Gets the value of the config option specified by name. If the key is
        found in the config, return the value. Otherwise, if a non-Sentinel
        default is given, return that. If after all that the key didn't match
        or the value wasn't found in the sources specified, throw KeyError.

        :param name: The config option name that corresponds with the option
            key in config.yml.
        :type name: str
        :param default: The default value to use if the name isn't a valid
            config or the config wasn't defined in the sources specified.
        :type default: Any
        :param sources: A list of sources to search in, defaults to all sources.
        :type sources: Optional[List[NavigatorOptionSource]]
        :return: The value of the config option specified.
        :rtype: Any
        """
        return self.get_with_origin(name, default, sources)[1]

    def get_with_origin(self, name: str, default: Any = Sentinel,
                        sources: Optional[List[NavigatorOptionSource]] = None) -> Tuple[NavigatorOptionSource, Any]:
        """
        Gets the value of the config option specified by name and the origin of
        where it was set.

        :param name: The config option name that corresponds with the option
            key in config.yml.
        :type name: str
        :param default: The default value to use if the name isn't a valid
            config or the config wasn't defined in the sources specified.
        :type default: Any
        :param sources: A list of sources to search in, defaults to all sources.
        :type sources: Optional[List[NavigatorOptionSource]]
        :return: The origin and value of the config option specified.
        :rtype: Tuple[NavigatorOptionSource, Any]
        """
        if name not in self._values:
            if default == Sentinel:
                raise KeyError(name)

            return default

        if sources is None:
            # Default is explicit > cli > env > config
            sources = [
                NavigatorOptionSource.EXPLICIT,
                NavigatorOptionSource.CLI,
                NavigatorOptionSource.ENVIRONMENT,
                NavigatorOptionSource.USER_CFG,
                NavigatorOptionSource.DEFAULT,
            ]

        source, value = self._values[name].get_value(sources)
        if value == Sentinel:
            if default == Sentinel:
                raise KeyError(name)

            value = default

        return source, value

    def set(self, name: str, value: Any):
        """
        Set an explicit config value for use in ansible-navigator. If the
        config option does not exist then KeyError is raised.

        :param name: The config name to set the value for.
        :type name: str
        :param value: The value to explicit set.
        :type value: Any
        """
        if name not in self._values:
            raise KeyError(name)

        self._values[name].set_value(value, NavigatorOptionSource.EXPLICIT)

    def get_argparse_info(self, name) -> Tuple[List, Dict]:
        """
        Gets the argparse definition for the config option specified.

        :param name: The config name to add as an argument.
        :type name: str
        :return: The args and kwargs to use for argparse add_argument().
        :rtype: Tuple[List, Dict]
        """
        if name not in self._values:
            raise KeyError(name)

        definition = self._def[name]

        # The current sole dict type is set-environment-variables and it's provided as a list in the form KEY=value.
        is_list_cli_value = definition['type'] in ['dict', 'list']

        args = [d['name'] for d in definition['cli']]
        kwargs = {
            'help': definition['description'],
            'default': [Sentinel] if is_list_cli_value else Sentinel,
            'dest': definition['cli_opts']['dest'],
        }

        if not definition['cli_opts']['nargs'] is None:
            kwargs['nargs'] = definition['cli_opts']['nargs']
        elif is_list_cli_value:
            kwargs['action'] = 'append'
            kwargs['nargs'] = '+'

        if definition['type'] == 'str':
            kwargs['type'] = str

        elif definition['type'] == 'bool':
            kwargs['type'] = argparse_bool

        elif definition['type'] == 'path':
            kwargs['type'] = argparse_path

        # Not having - or -- on the name means we have a positional parameter
        # and dest is the args[0] that is used.
        if not any([n for n in args if n.startswith('-')]):
            del kwargs['dest']

        if definition['choices']:
            kwargs['choices'] = definition['choices']

        return args, kwargs

    def load_argparse_results(self, args: Namespace):
        for name, definition in self._def.items():
            argparse_dest = definition['cli_opts']['dest']
            arg_value = getattr(args, argparse_dest, Sentinel)

            # List args are added as a list within a list, flatten it and remove the sentinel values
            if isinstance(arg_value, list):
                arg_value = [v for v in flatten_list(arg_value) if v != Sentinel]
                if not arg_value:
                    continue

            elif arg_value == Sentinel:
                continue

            # Need to manually convert the list KEY=value to a dict
            if definition['type'] == 'dict':
                dict_value = {}

                for env_var in arg_value:
                    parts = env_var.split("=", 1)
                    if len(parts) != 2:
                        raise ValueError(f"The following set-environment variable "
                                         f"entry could not be parsed: {env_var}")

                    dict_value[parts[0]] = parts[1]

                arg_value = dict_value

            config_value = self._values[name]
            config_value.set_value(arg_value, NavigatorOptionSource.CLI)
