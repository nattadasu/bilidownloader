# BiliDownloader

Assist you in ripping episode from BiliIntl.

> [!CAUTION]
> This tool is provided "as is" and solely for educational purposes.
>
> No warranties, express or implied, are made regarding its functionality or suitability for any particular purpose.
>
> The distribution or use of any final output generated by this tool for public or commercial purposes is strictly prohibited and strongly discouraged.
>
> The creators and distributors of this tool disclaim any liability for damages or losses arising from its use.

## Requirements

This tool requires following libraries/programs to be installed first:

* Python => 3.11
* Latest FFmpeg, and available on PATH
* MKVToolNix, not containerized (Flatpak, Snap, etc) and available on PATH. `mkvpropedit` must be available from the bundle.
* `pipx` (install with `pip install pipx`)

Additionally, you also required to obtain your own cookie.txt from BiliIntl and
Premium is activated as well.

## Installation

```bash
pipx install git+https://github.com/nattadasu/bilidownloader.git
```

## Usage

Simply call `bilidownloader` from your terminal! The program used Typer to build
CLI, so anything is properly documented by simply dding `--help` param.

### What it can do

* Download episode
* Get latest schedule
* Monitor and *automatically* download episode for tracked series (watchlist)

### What it CAN'T do

* Bypassing premium: you'd still requires one as cookie.txt
* Background check: use `crontab` to manage the watchlist instead
* Downloads user-uploaded content. The program was specifically tailored for
  episode URLs instead
* Ripping Mainland version. This program only tested to be used for International
  version
* Automatically manage the episode to dedicated folders: use FileBot instead.

## License

This repository is licensed under the GNU General Public License, version 3.0 or
later (GPL-3.0-or-later).

You may redistribute and/or modify the contents of this repository under the
terms of the GPL-3.0-or-later.

A copy of the license can be found in the LICENSE file or at
https://www.gnu.org/licenses/gpl-3.0.html.
