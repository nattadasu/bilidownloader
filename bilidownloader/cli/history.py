from sys import exit
from typing import Annotated, List, Optional

import typer
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Column, Table

from bilidownloader.cli.application import hi_app
from bilidownloader.cli.options import (
    ASSUMEYES_OPT,
    DEFAULT_HISTORY,
    HISTORY_OPT,
    HistorySortBy,
)
from bilidownloader.commons.ui import prn_error, prn_info
from bilidownloader.history.history import History

console = Console()


@hi_app.command(
    "list",
    help="Display the history of downloaded episodes. Alias: ls, l",
)
@hi_app.command("ls", help="Display the history of downloaded episodes", hidden=True)
@hi_app.command("l", help="Display the history of downloaded episodes", hidden=True)
def history_list(
    file_path: HISTORY_OPT = DEFAULT_HISTORY,
    sort_by: Annotated[
        HistorySortBy,
        typer.Option("--sort-by", help="Sort by field"),
    ] = HistorySortBy.DATE,
):
    hi = History(file_path)

    if len(hi.list) == 0:
        prn_error("Your download history is empty!")
        exit(2)

    prn_info("Here is the list of downloaded episodes:\n")

    # Sort based on user choice
    if sort_by == HistorySortBy.TITLE:
        items = sorted(hi.list, key=lambda x: x[2])  # Sort by series title
    elif sort_by == HistorySortBy.SERIES_ID:
        items = sorted(hi.list, key=lambda x: x[1])  # Sort by series ID
    elif sort_by == HistorySortBy.EPISODE_ID:
        items = sorted(hi.list, key=lambda x: x[4])  # Sort by episode ID
    else:  # date (default)
        items = sorted(
            hi.list, key=lambda x: x[0], reverse=True
        )  # Sort by timestamp, newest first

    table = Table(
        Column("No.", justify="right"),
        "Series Title",
        Column("Series ID", justify="right"),
        Column("Ep. #", justify="right"),
        Column("Episode ID", justify="right"),
        "Downloaded",
        box=box.ROUNDED,
    )
    for index, item in enumerate(items):
        timestamp, series_id, series_title, episode_idx, episode_id = item
        date_str = hi.format_timestamp(timestamp, use_rich=True)
        table.add_row(
            str(index + 1),
            series_title,
            series_id,
            episode_idx or "—",
            episode_id,
            date_str,
        )
    console.print(table)


@hi_app.command(
    "query",
    help="Search history by series title, ID, or episode ID. Alias: q, search, find",
)
@hi_app.command("q", help="Search history", hidden=True)
@hi_app.command("search", help="Search history", hidden=True)
@hi_app.command("find", help="Search history", hidden=True)
def history_query(
    query: Annotated[
        str,
        typer.Argument(help="Search query (series title, series ID, or episode ID)"),
    ],
    file_path: HISTORY_OPT = DEFAULT_HISTORY,
    sort_by: Annotated[
        HistorySortBy,
        typer.Option("--sort-by", help="Sort by field"),
    ] = HistorySortBy.DATE,
):
    hi = History(file_path)

    if len(hi.list) == 0:
        prn_error("Your download history is empty!")
        exit(2)

    # Try to search by series title first (fuzzy match), then by IDs
    results = hi.search_history(series_title=query)

    # If no fuzzy title matches, try exact ID matches
    if not results:
        results = hi.search_history(series_id=query)
    if not results:
        results = hi.search_history(episode_id=query)

    if not results:
        prn_error(f"No history entries found matching: {query}")
        exit(2)

    prn_info(f"Found {len(results)} matching entries:\n")

    # Sort based on user choice
    if sort_by == HistorySortBy.TITLE:
        items = sorted(results, key=lambda x: x[2])  # Sort by series title
    elif sort_by == HistorySortBy.SERIES_ID:
        items = sorted(results, key=lambda x: x[1])  # Sort by series ID
    elif sort_by == HistorySortBy.EPISODE_ID:
        items = sorted(results, key=lambda x: x[4])  # Sort by episode ID
    else:  # date (default)
        items = sorted(
            results, key=lambda x: x[0], reverse=True
        )  # Sort by timestamp, newest first

    table = Table(
        Column("No.", justify="right"),
        "Series Title",
        Column("Series ID", justify="right"),
        Column("Ep. #", justify="right"),
        Column("Episode ID", justify="right"),
        "Downloaded",
        box=box.ROUNDED,
    )
    for index, item in enumerate(items):
        timestamp, series_id, series_title, episode_idx, episode_id = item
        date_str = hi.format_timestamp(timestamp, use_rich=True)
        table.add_row(
            str(index + 1),
            series_title,
            series_id,
            episode_idx or "—",
            episode_id,
            date_str,
        )
    console.print(table)


@hi_app.command("clear", help="Clear history. Alias: clean, purge, cls, del, rm")
@hi_app.command("clean", help="Clear history", hidden=True)
@hi_app.command("purge", help="Clear history", hidden=True)
@hi_app.command("cls", help="Clear history", hidden=True)
@hi_app.command("del", help="Clear history", hidden=True)
@hi_app.command("rm", help="Clear history", hidden=True)
def history_clear(
    yes: ASSUMEYES_OPT = False,
    file_path: HISTORY_OPT = DEFAULT_HISTORY,
    by_series: Annotated[
        Optional[str],
        typer.Option(
            "--by-series",
            "-s",
            help="Clear history for a specific series (fuzzy match on title or exact match on ID)",
        ),
    ] = None,
    by_date: Annotated[
        Optional[str],
        typer.Option(
            "--by-date",
            "-d",
            help="Clear history older than specified date (YYYY-MM-DD format)",
        ),
    ] = None,
    by_episode: Annotated[
        Optional[List[str]],
        typer.Option(
            "--by-episode",
            "-e",
            help="Clear history for specific episode ID(s). Can be specified multiple times.",
        ),
    ] = None,
):
    hi = History(file_path)

    # Handle by_series option
    if by_series:
        prn_info(f"Searching for series matching: {by_series}")
        hi.purge_by_series(by_series, interactive=False)
        return

    # Handle by_date option
    if by_date:
        prn_info(f"Purging entries older than: {by_date}")
        try:
            hi.purge_by_date(by_date)
        except ValueError as e:
            prn_error(str(e))
            exit(1)
        return

    # Handle by_episode option
    if by_episode:
        prn_info(f"Deleting history entries for episode ID(s): {', '.join(by_episode)}")
        hi.purge_by_episode_id(by_episode)
        return

    # If no options provided and not assumeyes, offer interactive selection
    if not yes and len(hi.list) > 0:
        try:
            import survey

            action = survey.routines.select(
                "What would you like to do?",
                options=[
                    "Select specific episodes to delete",
                    "Clear all history",
                    "Cancel",
                ],
            )

            if action == 0:  # Select specific episodes
                # Create options for multiselect
                options = []
                for (
                    timestamp,
                    series_id,
                    series_title,
                    episode_idx,
                    episode_id,
                ) in hi.list:
                    date_str = hi.format_timestamp(timestamp)
                    ep_display = f"Ep. {episode_idx}" if episode_idx else "Ep. —"
                    options.append(
                        f"{series_title} ({ep_display}, ID: {episode_id}) - {date_str}"
                    )

                selected_indices: list[int] = survey.routines.basket(  # type: ignore
                    "Select episodes to delete (use Space to select, Enter to confirm):",
                    options=options,
                )

                if selected_indices and len(selected_indices) > 0:
                    # Extract episode IDs from selected indices
                    episode_ids = [hi.list[i][4] for i in selected_indices]
                    prn_info(f"Deleting {len(episode_ids)} episode(s)...")
                    hi.purge_by_episode_id(episode_ids)
                else:
                    prn_info("No episodes selected, cancelling.")
                return
            elif action == 1:  # Clear all history
                prompt_yes: bool = survey.routines.inquire(  # type: ignore
                    "Are you sure you want to clear ALL history? ", default=False
                )
                if prompt_yes:
                    hi.purge_all(confirm=False)
                    prn_info("History successfully cleared!")
                return
            else:  # Cancel
                prn_info("Operation cancelled.")
                return
        except (survey.widgets.Escape, KeyboardInterrupt):
            prn_info("Operation cancelled.")
            return

    # Default: clear all (when --assumeyes is used)
    if yes:
        hi.purge_all(confirm=False)
        prn_info("History successfully cleared!")


@hi_app.command(
    "stats", help="Show download history statistics. Alias: statistics, info"
)
@hi_app.command("statistics", help="Show download history statistics", hidden=True)
@hi_app.command("info", help="Show download history statistics", hidden=True)
def history_statistics(
    file_path: HISTORY_OPT = DEFAULT_HISTORY,
):
    hi = History(file_path)

    if len(hi.list) == 0:
        prn_error("Your download history is empty!")
        exit(2)

    stats = hi.get_statistics()
    term_width = console.width

    # Create overview panel
    overview_text = f"""[bold cyan]Total Episodes:[/bold cyan] {stats["total_episodes"]}
[bold cyan]Unique Series:[/bold cyan] {stats["unique_series"]}
[bold cyan]Avg per Series:[/bold cyan] {stats["average_per_series"]}"""

    overview_panel = Panel(
        overview_text,
        title="[bold]Overview[/bold]",
        border_style="cyan",
        expand=False,
    )

    # Create activity panel
    activity_text = f"""[bold cyan]First Download:[/bold cyan] {stats["first_download"]}
[bold cyan]Last Download:[/bold cyan] {stats["last_download"]}
[bold cyan]Last 7 days:[/bold cyan] {stats["downloads_last_7_days"]}
[bold cyan]Last 30 days:[/bold cyan] {stats["downloads_last_30_days"]}
[bold cyan]Most Active Day:[/bold cyan] {stats["most_active_day"]}
[dim]({stats["most_active_day_count"]} episodes)[/dim]"""

    activity_panel = Panel(
        activity_text,
        title="[bold]Activity[/bold]",
        border_style="cyan",
        expand=False,
    )

    # Create top series panel
    if stats["top_series"]:
        top_series_text = ""
        for i, (title, count) in enumerate(stats["top_series"], 1):
            top_series_text += f"{i}. {title}\n   [dim]{count} episode(s)[/dim]\n"
        top_series_text = top_series_text.rstrip("\n")
    else:
        top_series_text = "[dim]No data available[/dim]"

    top_series_panel = Panel(
        top_series_text,
        title="[bold]Top Series[/bold]",
        border_style="cyan",
        expand=False,
    )

    # Layout based on terminal width
    if term_width >= 120:
        # Three-column layout for wide terminals
        console.print(
            Columns(
                [overview_panel, activity_panel, top_series_panel],
                equal=False,
                expand=False,
            )
        )
    elif term_width >= 80:
        # Two-column layout with top series below
        console.print(
            Columns([overview_panel, activity_panel], equal=False, expand=False)
        )
        console.print(top_series_panel)
    else:
        # Single-column layout
        console.print(overview_panel)
        console.print(activity_panel)
        console.print(top_series_panel)
