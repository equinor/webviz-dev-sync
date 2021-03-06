from typing import Optional
import pathlib
import os
import sys
from pkg_resources import get_distribution, Distribution

from git import Repo, Remote
from git.exc import InvalidGitRepositoryError

from ._config_file import ConfigFile
from ._github_manager import GithubManager
from ._cache import Cache

from ._exec import exec, check_output
from ._log import log_message

def get_dist_egg_link(dist: Distribution) -> Optional[str]:
    """Is distribution an editable install?"""
    for path_item in sys.path:
        egg_link = os.path.join(path_item, dist.project_name + '.egg-link')
        if os.path.isfile(egg_link):
            egg_link
    return None


class MissingPackageInConfigFile(Exception):
    """Raised when a package is missing in the config file."""

    pass


class PackageManager:
    def __init__(self, name: str) -> None:
        self._name = name
        self._config = ConfigFile().get_package(name)
        self._github_manager = None
        self._repo: Optional[Repo] = None
        self._branch = None
        self._cache = Cache()

        if not self._config:
            raise MissingPackageInConfigFile(self._name)

        repo_storage_directory = ConfigFile().get_repo_storage_directory()

        log_message(f"\n\nInitializing '{self._name}'...")
        if self.is_local_package():
            self._path = pathlib.Path(self._config["local_path"])
        elif repo_storage_directory:
            log_message(
                f"Checking out Git repository from '{self._config['github_branch']['repository']}'..."
            )
            self._path = pathlib.Path.joinpath(repo_storage_directory, self._name)
            if not self._path.exists():
                self._path.mkdir()

            self._github_manager = GithubManager(ConfigFile().get_github_access_token())

            self.checkout()
            log_message(f"\u2713 Checkout complete")

    def checkout(self) -> None:
        if self._config is None:
            raise MissingPackageInConfigFile(self._name)

        if self._github_manager and self._path:
            self._github_manager.open_repo(self._config["github_branch"]["repository"])
            clone_url = self._github_manager.get_clone_url()

            try:
                self._repo = Repo(self._path)
                remote = Remote(
                    self._repo,
                    self._config["github_branch"]["repository"].split("/")[0],
                )
                if not remote.exists():
                    remote = remote.add(
                        repo=self._repo,
                        name=self._config["github_branch"]["repository"].split("/")[0],
                        url=clone_url,
                    )

                self._repo = remote.repo
            except InvalidGitRepositoryError:
                self._repo = Repo.clone_from(clone_url, self._path)
                remote = self._repo.remote()
                remote.rename(self._config["github_branch"]["repository"].split("/")[0])

            remote.fetch()

            self._repo.git.checkout(
                self._config["github_branch"]["repository"].split("/")[0]
                + "/"
                + self._config["github_branch"]["branch"]
            )

    def get_last_modified_date(self) -> float:
        return os.path.getmtime(self._path)

    def is_node_package(self) -> bool:
        return pathlib.Path.joinpath(self._path, "react").is_dir()

    def is_local_package(self) -> bool:
        if self._config is None:
            return False
        return "local_path" in self._config

    def install(self) -> None:
        if self._cache.get_package_modified_timestamp(
            self._name, self.is_local_package()
        ) < os.path.getmtime(self._path):
            log_message(f"\n\nInstalling '{self._name}'...")
            if sys.platform.startswith("win"):
                exec(
                    ["npm", "config", "set", "script-shell", "powershell"],
                    shell=True,
                    cwd=self._path,
                )
                log_message("Successfully set npm script-shell to powershell.")
            dist = get_distribution(self._name)
            if dist:
                egg_link = get_dist_egg_link(dist)
                if egg_link:
                    log_message("Removing egg link...")
                    os.remove(egg_link)
                    log_message("\u2713 Removed")
                
            self.execute_package_specific_installation_routine()
            self._cache.store_package_modified_timestamp(
                self._name, self.is_local_package()
            )

    def execute_package_specific_installation_routine(self) -> None:
        raise NotImplementedError

    def execute_package_specific_build_routine(self) -> None:
        raise NotImplementedError

    def get_build_timestamp(self) -> float:
        raise NotImplementedError

    def build(self) -> None:
        if (
            self._cache.get_package_build_timestamp(self._name, self.is_local_package())
            < self.get_build_timestamp()
        ):
            log_message(f"\n\nBuilding '{self._name}'...")
            self.execute_package_specific_build_routine()
            self._cache.store_package_built_timestamp(
                self._name, self.is_local_package()
            )

    def is_linked(self) -> bool:
        linked_packages = check_output(
            ["npm", "ls", "-g", "--depth=0", "--link=true"],
            cwd=self._path,
            shell=True,
        )
        path = (
            str(self._path)[0 : len(str(self._path)) - 1]
            if str(self._path)[len(str(self._path)) - 1] == "/"
            else str(self._path)
        )
        return path in str(linked_packages)

    def is_linked_to(self, other_package: str, other_package_path: str = "") -> bool:
        packages = check_output(
            ["npm", "list"],
            cwd=self._path.joinpath("react"),
            shell=True,
        )
        path = (
            other_package_path[0 : len(other_package_path) - 1]
            if other_package_path[len(other_package_path) - 1] == "/"
            else other_package_path
        )
        for line in str(packages).split("\\n"):
            if other_package in line and (path in line or other_package_path == ""):
                return True
        return False

    def shall_be_linked(self) -> bool:
        if self._config is None:
            return False
        return not (
            "link_package" in self._config and self._config["link_package"] == False
        )

    @property
    def path(self) -> pathlib.Path:
        return self._path
