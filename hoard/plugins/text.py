"""Render plain-text files to an image in a monospace font.

The first hoard render plugin. See plugins.py for the plugin contract.
Extending it to more text types is just a matter of adding extensions to
match_extensions() below.
"""
import io
import os

from PIL import Image, ImageColor, ImageDraw, ImageFont

from config import config

_FONT_PATH = os.path.join('resources', 'DejaVuSansMono.ttf')
_FONT_SIZE = 16
_FG        = (200, 200, 200)   # text colour (light, for the dark thumb background)
_PAD       = 12                # px margin around the text
_MAX_LINES = 100               # full-view safety cap (avoids huge images)
_MAX_COLS  = 120               # truncate very long lines
_TN_LINES  = 22                # lines rendered into a thumbnail preview
_TN_COLS   = 72                # columns rendered into a thumbnail preview
_MAX_W     = 4000              # px clamps so a pathological file can't blow up memory
_MAX_H     = 60000


def match_extensions():
	return (
		'.bat',
		'.cmd',
		'.conf',
		'.csv',
		'.gitignore',
		'.htaccess',
		'.html',
		'.ini',
		'.js',
		'.json',
		'.log',
		'.md',
		'.php',
		'.prg',
		'.ps',
		'.py',
		'.tsv',
		'.txt',
		)


def render(server_path: str) -> tuple[bytes, str]:
	img = _render(server_path, _MAX_LINES)
	buf = io.BytesIO()
	img.save(buf, format='PNG')
	return buf.getvalue(), 'image/png'


def render_thumbnail(server_path: str, size) -> bytes:
	# render just the first lines; handle_thumbnail's pipeline rescales to `size`
	img = _render(server_path, _TN_LINES)
	buf = io.BytesIO()
	img.save(buf, format='PNG')
	return buf.getvalue()


def _load_font() -> ImageFont.FreeTypeFont:
	try:
		return ImageFont.truetype(_FONT_PATH, _FONT_SIZE)
	except Exception:
		# bundled font missing — fall back to PIL's default (not monospace)
		return ImageFont.load_default(size=_FONT_SIZE) # type: ignore


def _read_lines(path: str, max_lines: int) -> list[str]:
	lines: list[str] = []
	truncated = False
	with open(path, 'r', encoding='utf-8', errors='replace') as f:
		for i, raw in enumerate(f):
			if i >= max_lines:
				truncated = True
				break
			line = raw.rstrip('\r\n').replace('\t', '    ')
			if len(line) > _MAX_COLS:
				line = line[:_MAX_COLS] + '…'
			lines.append(line)
	if truncated:
		lines.append('')
		lines.append(f'… (truncated at {max_lines} lines)')
	return lines or ['(empty file)']


def _render(path: str, max_lines: int) -> Image.Image:
	font  = _load_font()
	lines = _read_lines(path, max_lines)

	ascent, descent = font.getmetrics()
	line_h = ascent + descent + 4
	char_w = font.getlength('M') or _FONT_SIZE * 0.6  # monospace: one advance for all
	cols   = min(max((len(l) for l in lines), default=1), _TN_COLS)

	width  = max(1, min(int(char_w * cols) + _PAD * 2, _MAX_W))
	height = max(1, min(line_h * len(lines) + _PAD * 2, _MAX_H))

	bg  = ImageColor.getrgb(config('thumbBackgroundColor'))
	img = Image.new('RGB', (width, height), bg)
	draw = ImageDraw.Draw(img)
	y = _PAD
	for line in lines:
		draw.text((_PAD, y), line, font=font, fill=_FG)
		y += line_h
	return img
