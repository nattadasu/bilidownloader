import os
import platform
import subprocess as sp
import sys
from pathlib import Path

import psutil
import typer
from rich import print as rprint

from bilidownloader.cli.application import app
from bilidownloader.commons.constants import BASE_DIR


def _get_user_shell() -> list[str]:
    """
    Detect the user's shell and return appropriate command.

    Tries in order:
    1. Environment variables that indicate the current shell
    2. STARSHIP_SHELL if present
    3. Parent process name
    4. SHELL environment variable (Unix)
    5. System defaults

    Returns:
        List containing the shell command to execute
    """
    import shutil

    # 1. Check shell-specific environment variables
    shell_env_vars = {
        "NU_VERSION": "nu",
        "XONSH_VERSION": "xonsh",
        "FISH_VERSION": "fish",
        "ZSH_VERSION": "zsh",
        "BASH_VERSION": "bash",
        "PSModulePath": "pwsh",  # PowerShell Core (cross-platform)
    }

    for env_var, shell_name in shell_env_vars.items():
        if os.environ.get(env_var):
            shell_path = shutil.which(shell_name)
            if shell_path:
                return [shell_name]

    # 2. Check STARSHIP_SHELL (if user uses Starship prompt)
    starship_shell = os.environ.get("STARSHIP_SHELL")
    if starship_shell:
        # Normalize shell name
        shell_map = {
            "nu": "nu",
            "nushell": "nu",
            "elvish": "elvish",
            "xonsh": "xonsh",
            "fish": "fish",
            "zsh": "zsh",
            "bash": "bash",
            "pwsh": "pwsh",
            "powershell": "pwsh",
        }
        shell_name = shell_map.get(starship_shell.lower(), starship_shell)
        shell_path = shutil.which(shell_name)
        if shell_path:
            return [shell_name]

    # 3. Try to detect from parent process
    try:
        parent = psutil.Process(os.getppid())
        parent_name = parent.name().lower()

        # Remove common suffixes
        for suffix in [".exe", "-bin"]:
            if parent_name.endswith(suffix):
                parent_name = parent_name[: -len(suffix)]

        # Check if parent is a known shell
        known_shells = [
            "nu",
            "nushell",
            "elvish",
            "xonsh",
            "fish",
            "zsh",
            "bash",
            "pwsh",
            "powershell",
            "sh",
        ]

        if parent_name in known_shells:
            # Normalize name
            if parent_name in ["nushell"]:
                parent_name = "nu"
            elif parent_name in ["powershell"]:
                parent_name = "pwsh"

            shell_path = shutil.which(parent_name)
            if shell_path:
                return [parent_name]
    except (ImportError, Exception):
        # psutil not available or failed, continue with fallbacks
        pass

    # 4. Unix-like systems - use SHELL environment variable
    if platform.system() != "Windows":
        shell = os.environ.get("SHELL")
        if shell:
            return [shell]
        # Fallback to sh
        return ["/bin/sh"]

    # 5. Windows fallbacks
    # Try PowerShell 5.x (Windows-only)
    if shutil.which("powershell"):
        return ["powershell.exe"]
    # CMD as last resort
    return ["cmd.exe"]


def _open_directory(directory: Path, cd: bool, show: bool) -> None:
    """
    Internal function to open a directory, spawn a shell, or print its path.

    Args:
        directory: Path to the directory to open or print
        cd: If True, spawn a new shell in the directory
        show: If True, print the path instead of opening
    """
    # Ensure directory exists
    directory.mkdir(parents=True, exist_ok=True)

    # Print path for command substitution
    if show:
        print(directory)
        return

    # Spawn a new shell in the directory
    if cd:
        shell = _get_user_shell()
        shell_name = os.path.basename(shell[0])
        rprint(f"[green]Launching {shell_name} in:[/green] [cyan]{directory}[/cyan]")
        rprint("[dim]Type 'exit' or press Ctrl+D to return to the previous shell[/dim]")

        try:
            # Run shell with working directory set
            result = sp.run(shell, cwd=str(directory))

            # Notify user that they've exited the shell
            rprint(f"[green]Exited {shell_name} shell[/green]")
            rprint("[dim]Returned to previous directory[/dim]")
            sys.exit(result.returncode)
        except FileNotFoundError:
            rprint(f"[red]Error: Could not find shell: {shell[0]}[/red]")
            rprint(f"User data directory: [cyan]{directory}[/cyan]")
            sys.exit(1)
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            rprint("\n[yellow]Shell interrupted[/yellow]")
            sys.exit(130)
        except Exception as e:
            rprint(f"[red]Error launching shell:[/red] {e}")
            rprint(f"User data directory: [cyan]{directory}[/cyan]")
            sys.exit(1)

    # Open directory in file manager
    system = platform.system()

    try:
        if system == "Windows":
            # Windows: use explorer
            sp.run(["explorer", str(directory)], check=True)
        elif system == "Darwin":
            # macOS: use open
            sp.run(["open", str(directory)], check=True)
        elif system == "Linux":
            # Linux: try xdg-open
            sp.run(["xdg-open", str(directory)], check=True)
        else:
            # Unsupported system
            rprint(f"[yellow]Cannot automatically open directory on {system}.[/yellow]")
            rprint(f"User data directory: [cyan]{directory}[/cyan]")
            sys.exit(1)

        rprint(f"[green]Opened user data directory:[/green] [cyan]{directory}[/cyan]")
    except FileNotFoundError:
        rprint(
            f"[red]Error: Could not find file manager application for {system}.[/red]"
        )
        rprint(f"User data directory: [cyan]{directory}[/cyan]")
        sys.exit(1)
    except sp.CalledProcessError as e:
        rprint(f"[red]Error opening directory:[/red] {e}")
        rprint(f"User data directory: [cyan]{directory}[/cyan]")
        sys.exit(1)


ARG_CD = typer.Option(
    False,
    "--cd",
    help="Launch a shell in the user data directory",
)

ARG_SHOW = typer.Option(
    False,
    "--show",
    "-s",
    help="Print the directory path for use with cd command",
)


@app.command(
    name="userdir",
    help="Open user data directory, spawn shell, or print path. Alias: cfgd, config-dir",
    short_help="Open or show user data directory",
)
def userdir(cd: bool = ARG_CD, show: bool = ARG_SHOW):
    """
    Open the user data directory in the file manager, spawn a shell, or print the path.

    The user data directory contains configuration files such as cookies.txt,
    watchlist.txt, and history.v2.tsv.

    By default (no flags), opens the directory in your file manager.

    With --cd, launches a new shell session in the directory.
    With --show, prints the directory path for use with command substitution.

    Examples:
        bilidownloader userdir          # Opens in file manager
        bilidownloader userdir --cd     # Spawns shell in directory
        cd $(bilidownloader userdir --show)  # Change to directory
    """
    _open_directory(BASE_DIR, cd, show)


# Add aliases
@app.command(
    name="cfgd",
    help="Open user data directory, spawn shell, or print path",
    hidden=True,
)
def cfgd(cd: bool = ARG_CD, show: bool = ARG_SHOW):
    """Alias for userdir command."""
    _open_directory(BASE_DIR, cd, show)


@app.command(
    name="config-dir",
    help="Open user data directory, spawn shell, or print path",
    hidden=True,
)
def config_dir(cd: bool = ARG_CD, show: bool = ARG_SHOW):
    """Alias for userdir command."""
    _open_directory(BASE_DIR, cd, show)
