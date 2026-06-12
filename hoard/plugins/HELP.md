# Writing a hoard render plugin

A plugin teaches hoard a new file type — how to show it full-screen and how to
make its thumbnail — without touching any core code. Drop a `.py` file in this
`plugins/` directory and hoard discovers it on startup. After adding or editing
a plugin, press **Ctrl+R** in the server terminal to reload.

`text.py` is the bundled reference plugin; read it alongside this file.

## The contract

Name the file after the type it handles (`excel.py`, `psd.py`, …). Files whose
name starts with `_` are skipped. Your module must expose three callables:

```python
def match_extensions() -> Iterable[str]:
    # lowercase extensions, each with a leading dot
    return ('.txt', '.log', '.md')

def render(server_path: str) -> tuple[bytes, str]:
    # the full-view render: (image_bytes, mime)
    # mime MUST be an image type — the bytes go straight into the viewer <img>
    return png_bytes, 'image/png'

def render_thumbnail(server_path: str, size: tuple[int, int]) -> bytes:
    # a PIL-openable preview image (PNG bytes are easiest)
    # size is the thumbnail canvas, advisory only — see below
    return png_bytes
```

`server_path` is an absolute path to the file on disk. If any required function
is missing or not callable, the whole plugin is skipped (logged at startup).

## How hoard uses each function

- **`match_extensions()`** is read once at load. Every extension you return is
  registered to your module. If two plugins claim the same extension the last
  one loaded (alphabetical by filename) wins, and the override is logged.

- **`render()`** output is returned verbatim to the browser, so it must be an
  image the browser can display (`image/png`, `image/jpeg`, `image/webp`, …).
  v1 plugins always produce a still image — the file is classified `KIND_IMAGE`
  in the viewer.

- **`render_thumbnail()`** does **not** need to be pre-sized. Its bytes are fed
  into `handle_thumbnail`'s normal pipeline, which resizes to the configured
  `thumbnailWidthHeight`, letterboxes with `thumbBackgroundColor`, and stamps
  the filename/dimensions label. Return a small, cheap preview — for text,
  rendering only the first ~20 lines is plenty.

## Precedence

Plugins are consulted **before** the built-in handlers in `classify()`,
`handle_file.run()`, and `handle_thumbnail.run()`. That means a plugin can
override a built-in type (e.g. take over `.html`). Be deliberate about which
extensions you claim.

## Errors

A plugin that raises is logged (with traceback) and hoard falls back to the
built-in handling for that file — or to the generic "Can't render" thumbnail.
Your plugin can't crash the server, but a noisy one will spam `log.txt`, so
guard risky work and fail cleanly.

## What you can rely on

Plugins run inside the server process, so you can import core modules:

- `from config import config` — read `config.json` values (`text.py` pulls
  `thumbBackgroundColor` so its background matches the gallery).
- `from log import log` — append a line to `log.txt`.
- `resources/` holds bundled assets; `text.py` loads
  `resources/DejaVuSansMono.ttf` from there. Paths are relative to the server's
  working directory (`hoard/`), same as the rest of the app.

Pillow (`PIL`) is already a dependency, so it's the path of least resistance for
producing image bytes. Anything else your plugin needs must be installable in
the venv (add it to `requirements.txt`).

## Minimal example

```python
import io
from PIL import Image

def match_extensions():
    return ('.foo',)

def _image(server_path):
    # ... build a PIL Image representing the file ...
    return Image.new('RGB', (640, 480), (40, 40, 40))

def render(server_path):
    buf = io.BytesIO()
    _image(server_path).save(buf, format='PNG')
    return buf.getvalue(), 'image/png'

def render_thumbnail(server_path, size):
    buf = io.BytesIO()
    _image(server_path).save(buf, format='PNG')
    return buf.getvalue()
```

## Shipping it

`_build.cmd` copies files by an explicit allowlist. If you want a plugin to ride
along in a deploy, add it there — otherwise it stays local to your dev tree.
