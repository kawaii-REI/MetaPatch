\# MetaPatch v1.0



\*\*HEVC/x265 Metadata Patcher\*\* — A GUI tool to patch x265 encoder strings

in MKV/MP4 files, build HEVC option strings, remux via mkvmerge, and more.



\## Features

\- x265 encoder string patching (single \& batch)

\- Full HEVC options builder with 100+ parameters

\- mkvmerge remux pass

\- H.264 track remover

\- Custom preset maker

\- Animated splash screen

\- Light / Dark theme

\- Patch history (last 100 ops)



\## Requirements

\- Python 3.10+

\- `pip install customtkinter Pillow`

\- mkvmerge (optional, for remux features)



\## Run from source

```bash

pip install customtkinter Pillow

python metapatch.py

```



\## Build EXE yourself

```bash

pip install pyinstaller

pyinstaller --onefile --windowed --name MetaPatch \\

&#x20; --collect-all customtkinter \\

&#x20; --add-data "splash\_images;splash\_images" \\

&#x20; metapatch.py

```



\## Download

\[\*\*Latest Release →\*\*](../../releases/latest)



\## Image Credits

Splash screen wallpapers sourced from various sites.

See \[images\_credit.txt](images\_credit.txt) for full credits.

All wallpapers belong to their respective artists/owners.



\## License

MIT License — see \[LICENSE](LICENSE)

Software only. Wallpaper images are not covered by this license.

