from json import dumps
from typing import Any

from ass import parse_string as ass_loads
from yt_dlp.postprocessor import PostProcessor


class SSARescaler(PostProcessor):
    def run(self, info) -> tuple[list[Any], Any]:
        # Replace string from "Noto Sans,100" to "Noto Sans,65" on all
        # subtitle files
        def return_dump() -> tuple[list[Any], Any]:
            return [], info

        self.to_screen("Changing subtitle font size")
        fpath: dict[str, str] = info.get("__files_to_move", {})
        if len(fpath) == 0:
            self.report_error("No filepath found in the metadata")
            return return_dump()
        fonts: list[str] = []
        for _, sub_file in fpath.items():
            if not sub_file.endswith("ass"):
                self.report_warning(f"{sub_file} is skipped as it's not SSA file")
                continue
            try:
                with open(sub_file, "r", encoding="utf-8") as file:
                    content = file.read()
                    ass = ass_loads(content)
            except ValueError:
                with open(sub_file, "r", encoding="utf-8-sig") as file:
                    content = file.read()
                    ass = ass_loads(content)

            for style in ass.styles:
                if style.fontname not in fonts:
                    fonts.append(style.fontname)
                if style.fontsize == 100:
                    style.fontsize = 65
                if style.fontsize == 200:
                    style.fontsize = 100
            with open(sub_file, "w", encoding="utf-8") as file:
                ass.dump_file(file)
            self.to_screen(f"{sub_file} has been properly formatted")

        if len(fonts) > 0:
            with open("fonts.json", "w", encoding="utf-8") as file:
                file.write(dumps(fonts))

        return return_dump()
