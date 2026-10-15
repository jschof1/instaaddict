import logging
import os
import sys
from datetime import datetime
from typing import Optional

import configargparse
import yaml

from InstaAddict.core.plugin_loader import PluginLoader

logger = logging.getLogger(__name__)

# Handled by the 'run' subcommand in InstaAddict/__main__.py (systemd runs the bot with --no-supervisor)
LAUNCHER_ARGS = ("run", "--no-supervisor")


class Config:
    def __init__(self, first_run=False, **kwargs):
        if kwargs:
            self.args = kwargs
            self.module = True
        else:
            self.args = sys.argv
            self.module = False
        self.config = None
        self.config_list = None
        self.plugins = None
        self.actions = None
        self.enabled = []
        self.unknown_args = []
        self.debug = False
        self.device_id: Optional[str] = None
        self.app_id: Optional[str] = None
        self.first_run = first_run
        self.username = False

        # Pre-Load Variables Needed for Script Init
        if self.module:
            if "debug" in self.args:
                self.debug = True
            if "username" in self.args:
                self.username = self.args["username"]
            if "app_id" in self.args:
                app_id = self.args["app_id"]
                if app_id:
                    self.app_id = app_id
                else:
                    self.app_id = "com.instagram.android"
        else:
            if "--config" not in self.args and "--username" in self.args:
                try:
                    u_idx = self.args.index("--username")
                    if u_idx + 1 < len(self.args):
                        cand_user = self.args[u_idx + 1]
                        cand_cfg = os.path.join("accounts", cand_user, "config.yml")
                        if os.path.isfile(cand_cfg):
                            self.args.extend(["--config", cand_cfg])
                except Exception:
                    pass

            if "--config" in self.args:
                try:
                    file_name = self.args[self.args.index("--config") + 1]
                    if not file_name.endswith((".yml", ".yaml")):
                        logger.error(
                            f"You have to specify a *.yml / *.yaml config file path (For example 'accounts/your_account_name/config.yml')! \nYou entered: {file_name}, abort."
                        )
                        sys.exit(1)
                    logger.warning(get_time_last_save(file_name))
                    with open(file_name, encoding="utf-8") as fin:
                        # preserve order of yaml
                        self.config_list = [line.strip() for line in fin]
                        fin.seek(0)
                        # preload config for debug and username
                        self.config = yaml.safe_load(fin)
                except IndexError:
                    logger.warning(
                        "Please provide a filename with your --config argument. Example: '--config accounts/yourusername/config.yml'"
                    )
                    exit(2)
                except FileNotFoundError:
                    logger.error(
                        f"I can't see the file '{file_name}'! Double check the spelling or if you're calling the bot from the right folder. (You're there: '{os.getcwd()}')"
                    )
                    exit(2)

                self.username = self.config.get("username", False)
                self.debug = self.config.get("debug", False)
                self.app_id = self.config.get("app_id", "com.instagram.android")
            else:
                if "--debug" in self.args:
                    self.debug = True
                if "--username" in self.args:
                    try:
                        self.username = self.args[self.args.index("--username") + 1]
                    except IndexError:
                        logger.warning(
                            "Please provide a username with your --username argument. Example: '--username yourusername'"
                        )
                        exit(2)
                if "--app-id" in self.args:
                    self.app_id = self.args[self.args.index("--app-id") + 1]
                else:
                    self.app_id = "com.instagram.android"

        # Configure ArgParse
        self.parser = configargparse.ArgumentParser(
            config_file_open_func=lambda filename: open(
                filename, "r+", encoding="utf-8"
            ),
            description="InstaAddict Instagram Bot",
        )
        self.parser.add_argument(
            "--config",
            required=False,
            is_config_file=True,
            help="config file path",
        )

        # on first run, we must wait to proceed with loading
        if not self.first_run:
            self.load_plugins()
            self.parse_args()

    def load_plugins(self):
        self.plugins = PluginLoader("InstaAddict.plugins", self.first_run).plugins
        self.actions = {}
        for plugin in self.plugins:
            if plugin.arguments:
                for arg in plugin.arguments:
                    try:
                        arg_name = arg.get("arg")
                        if arg_name and arg_name in self.parser._option_string_actions:
                            logger.debug(
                                f"Argument '{arg_name}' already registered; skipping duplicate for {plugin.__class__.__name__}."
                            )
                            if arg.get("operation", False):
                                self.actions[arg_name[2:]] = plugin
                            continue

                        action = arg.get("action", None)
                        if action:
                            self.parser.add_argument(
                                arg["arg"],
                                help=arg["help"],
                                action=arg.get("action", None),
                            )
                        else:
                            kwargs = {
                                "nargs": arg.get("nargs", None),
                                "help": arg.get("help", None),
                                "default": arg.get("default", None),
                            }
                            if "metavar" in arg and arg["metavar"] is not None:
                                kwargs["metavar"] = arg["metavar"]
                            self.parser.add_argument(
                                arg["arg"],
                                **kwargs,
                            )
                        if arg.get("operation", False):
                            self.actions[arg["arg"][2:]] = plugin
                    except Exception as e:
                        logger.error(
                            f"Error while importing argument '{arg.get('arg', 'unknown')}' of plugin {plugin.__class__.__name__}: {e}"
                        )

    def parse_args(self):
        def _is_legacy_arg(arg):
            if arg in ["interact", "hashtag-likers"]:
                if self.first_run:
                    logger.warning(
                        f"You are using a legacy argument {arg} that is no longer supported. It will not be used. Please refer to https://docs.gramaddict.org/#/configuration?id=arguments."
                    )
                return True
            return False

        if self.module:
            if self.first_run:
                logger.debug("Arguments used:")
                if self.config:
                    logger.debug(f"Config used: {self.config}")
                if len(self.args) == 0:
                    self.parser.print_help()
                    exit(0)
        else:
            if self.first_run:
                logger.debug(f"Arguments used: {' '.join(sys.argv[1:])}")
                if self.config:
                    logger.debug(f"Config used: {self.config}")
                if len(sys.argv) <= 1:
                    self.parser.print_help()
                    exit(0)
        if self.module:
            arg_str = ""
            for k, v in self.args.items():
                new_key = k.replace("_", "-")
                new_key = f" --{new_key}"
                arg_str += f"{new_key} {v}"
            self.args, self.unknown_args = self.parser.parse_known_args(args=arg_str)
        else:
            self.args, self.unknown_args = self.parser.parse_known_args()
        # The 'run' subcommand and its launcher flags are parsed in __main__.py, not here: ignore them
        for launcher_arg in LAUNCHER_ARGS:
            while launcher_arg in self.unknown_args:
                self.unknown_args.remove(launcher_arg)
        if self.unknown_args and self.first_run:
            logger.error(
                "Unknown arguments: " + ", ".join(str(arg) for arg in self.unknown_args)
            )
            self.parser.print_help()
            for arg in self.unknown_args:
                if "detect-block" in arg:
                    logger.error(
                        "Please replace the line 'detect-block: true/false' in your config file *.yml with 'disable-block-detection: true/false'"
                    )
                    break
            exit(0)
        self.device_id = self.args.device
        # We need to maintain the order of plugins as defined
        # in config or sys.argv
        if self.config_list:
            for item in self.config_list:
                item = item.split(":")[0]
                if (
                    item in self.actions
                    and getattr(self.args, item.replace("-", "_")) is not None
                    and not _is_legacy_arg(item)
                ):
                    self.enabled.append(item)
        else:
            for item in sys.argv:
                nitem = item[2:]
                if (
                    nitem in self.actions
                    and getattr(self.args, nitem.replace("-", "_")) is not None
                    and not _is_legacy_arg(nitem)
                ):
                    self.enabled.append(nitem)


def get_time_last_save(file_path) -> str:
    try:
        absolute_file_path = os.path.abspath(file_path)
        timestamp = os.path.getmtime(absolute_file_path)
        last_save = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        return f"{file_path} has been saved last time at {last_save}"
    except FileNotFoundError:
        return f"File {file_path} not found"
