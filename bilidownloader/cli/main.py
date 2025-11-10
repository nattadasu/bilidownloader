from rich import print as rprint
from rich.console import Console

import bilidownloader.cli.download  # noqa
import bilidownloader.cli.schedule  # noqa
import bilidownloader.cli.today  # noqa
from bilidownloader.cli.application import app, hi_app, wl_app
from bilidownloader.metadata import __VERSION__
from bilidownloader.updater import check_for_updates

console = Console()

app.add_typer(hi_app, name="history", help="View and manage history. Alias: his, h")
app.add_typer(hi_app, name="his", help="View and manage history", hidden=True)
app.add_typer(hi_app, name="h", help="View and manage history", hidden=True)

wl_help = (
    "View and manage watchlist, or download recently released episodes from watchlist"
)
wl_shelp = "View and manage watchlist. Alias: wl"
app.add_typer(wl_app, name="watchlist", help=f"{wl_help}", short_help=wl_shelp)
app.add_typer(wl_app, name="wl", help=wl_help, hidden=True)


# check for an update
def app_update() -> bool:
    """Check for an update from upstream's pyproject.toml"""
    latest_version = __VERSION__
    update_url = "https://raw.githubusercontent.com/nattadasu/bilidownloader/main/pyproject.toml"
    try:
        resp = req.get(update_url)
        resp.raise_for_status()
        data = tloads(resp.text)
        latest_version = Version.parse(data["project"]["version"])
        current = Version.parse(__VERSION__)
        if latest_version > current:
            warn = (
                f"[bold]BiliDownloader[/] has a new version: [blue]{latest_version}[/] "
                f"(Current: [red]{__VERSION__}[/]).\n"
                "Updating is recommended to get the latest features and bug fixes.\n\n"
                "To update, execute [black]`[/][bold]pipx upgrade bilidownloader[black]`[/]"
            )
            panel = Panel(
                warn,
                title="Update Available",
                box=box.ROUNDED,
                title_align="left",
                border_style="yellow",
                expand=False,
            )
            console.print(panel)
            print()
    except Exception as err:
        panel = Panel(
            f"Failed to check for an app update, reason: {err}",
            title="Update Check Failed",
            box=box.ROUNDED,
            title_align="left",
            border_style="red",
            expand=False,
        )
        console.print(panel)
        print()
    rprint(f"[reverse white] BiliDownloader [/][reverse blue bold] {__VERSION__} [/]")
    return latest_version != __VERSION__


@app.callback()
def main():
    app_update()


if __name__ == "__main__":
    app()
