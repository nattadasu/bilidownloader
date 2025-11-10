# BiliDownloader

## Project Overview

This project, `BiliDownloader`, is a Python-based command-line tool designed to download videos from the international version of BiliBili.tv. It acts as a wrapper around the popular `yt-dlp` library, extending its functionality with features tailored for BiliBili. These include managing a watchlist of series, tracking release schedules, and maintaining a history of downloaded episodes.

The application is built using `typer` for its command-line interface, `requests` for interacting with the BiliBili API, `survey` for interactive prompts, and `rich` for enhanced terminal output. It requires Python 3.11 or higher, as well as the external tools `ffmpeg` and `mkvpropedit`.

## Building and Running

The project is intended to be installed and run directly from the command line using `pipx`.

### Installation

```bash
# Install the latest version from the git repository
pipx install git+https://github.com/nattadasu/bilidownloader.git

# To enable ASS subtitle support
pipx install 'bilidownloader[ass] @ git+https://github.com/nattadasu/bilidownloader.git'
```

### Running the application

Once installed, the application is run using the `bilidownloader` command:

```bash
bilidownloader --help
```

This will display the main help menu with all available commands and options.

### Key Commands

*   `bilidownloader download <URL>`: Downloads a video from a given BiliBili URL.
*   `bilidownloader today`: Shows a list of anime released today, allowing the user to select one to download.
*   `bilidownloader released`: Shows a list of anime released in the past three days for the user to select and download.
*   `bilidownloader schedule`: Displays the release schedule for the week.
*   `bilidownloader watchlist --help`: Manages the user's watchlist.
*   `bilidownloader history --help`: Manages the user's download history.

## Development Conventions

*   **Dependencies**: Project dependencies are managed in `pyproject.toml`.
*   **CLI**: The command-line interface is built with `typer`, with commands and subcommands organized in the `bilidownloader/__main__.py` file.
*   **API Interaction**: The `bilidownloader/api.py` module handles communication with the BiliBili API.
*   **Code Style**: The code appears to follow standard Python conventions.
*   **Versioning**: The project follows Semantic Versioning.
*   **Man Pages**: If there are any changes to command-line arguments, option flags, or configuration file parameters, the corresponding man pages located in the `man/` directory should be updated to reflect these changes.
