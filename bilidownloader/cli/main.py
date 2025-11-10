from rich import print as rprint
from rich.console import Console

import bilidownloader.cli.download  # noqa
import bilidownloader.cli.schedule  # noqa
import bilidownloader.cli.today  # noqa
from bilidownloader.cli.application import app, hi_app, wl_app
from bilidownloader.commons.metadata import __VERSION__
from bilidownloader.commons.updater import check_for_updates

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


@app.callback()
def main():
    check_for_updates()
    rprint(f"[reverse white] BiliDownloader [/][reverse blue bold] {__VERSION__} [/]")


if __name__ == "__main__":
    app()
