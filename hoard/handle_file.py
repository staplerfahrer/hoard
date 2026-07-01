import io
import os
import traceback
from PIL import Image, ImageColor, ImageOps
import filesystem as fs
import plugins
from config import config, config_get
from log import log


# PIL format name → MIME type (for image files PIL can identify)
_PIL_MIME: dict[str, str] = {
	'JPEG': 'image/jpeg',
	'PNG':  'image/png',
	'GIF':  'image/gif',
	'WEBP': 'image/webp',
	'BMP':  'image/bmp',
}

_PIL_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'})

def run(server_path: str, range_l: int | None, range_u: int | None, slow: bool = False) \
		-> tuple[bytes, str, int | None, int | None, int | None] | None:
	if not os.path.isfile(server_path):
		return None

	# render plugins take precedence over the built-in handlers
	plugin = plugins.plugin_for(server_path)
	if plugin is not None:
		try:
			data, mime = plugin.render(server_path)
			return data, mime, None, None, None
		except Exception:
			log(f'plugin render failed for {server_path}: {traceback.format_exc()}')
			return None

	ext = os.path.splitext(server_path)[1].lower()

	# slow client: re-encode any raster image to a small JPEG (transparency flattened)
	# to cut bandwidth. Skipped for vector (.svg). On failure, fall through to normal
	# handling below.
	if slow and ext in fs.IMAGE_EXTS and ext != '.svg':
		result = _slow_jpeg(server_path, ext)
		if result is not None:
			return result

	# convert raw files
	if ext in fs.RAW_EXTS:
		data = fs.dcraw_extract(server_path)
		return (data, 'image/jpeg', None, None, None) if data else None

	# serve non-images directly, potentially with range 206
	if ext in fs.NON_IMAGE_EXTS:
		data, mime, range_l, range_u, end = fs.serve_file(server_path, range_l, range_u)
		return data, mime, range_l, range_u, end

	# if another type not browser image
	if ext not in _PIL_EXTS:
		return _pil_convert(server_path)

	# totally unknown mime type
	if ext not in fs.MIME:
		return None

	# serve file with PIL mime
	data, mime, range_l, range_u, end = fs.serve_file(server_path, range_l, range_u)
	if range_l is None:  # full file in hand — refine the mime from the actual bytes
		mime = _pil_mime(data, mime)
	return data, mime, range_l, range_u, end


def _pil_mime(data: bytes, fallback: str) -> str:
	"""Correct the mime from the image's real format (e.g. a .jpg that's actually a
	PNG). Reads only the header from the bytes already in memory — no extra disk read."""
	try:
		with Image.open(io.BytesIO(data)) as img:
			return _PIL_MIME.get(img.format or '', fallback)
	except Exception:
		log(f'handle_file PIL: {traceback.format_exc()}')
		return fallback


def _pil_convert(server_path: str) \
		-> tuple[bytes, str, int | None, int | None, int | None] | None:
	try:
		with Image.open(server_path) as img:
			if img.mode == 'CMYK':
				img = img.convert('RGB')

			has_alpha = img.mode in ('RGBA', 'LA', 'PA') or \
				(img.mode == 'P' and 'transparency' in img.info)

			buf = io.BytesIO()

			if has_alpha:
				img.convert('RGBA').save(buf, format='PNG')
				mime = 'image/png'
			else:
				img.convert('RGB').save(buf, format='JPEG')
				mime = 'image/jpeg'

			return buf.getvalue(), mime, None, None, None
	except Exception:
		log(f'handle_file PIL convert: {traceback.format_exc()}')
		return None


def _slow_jpeg(server_path: str, ext: str) \
		-> tuple[bytes, str, int | None, int | None, int | None] | None:
	"""Re-encode an image to a low-quality JPEG for a slow client, flattening any
	transparency onto thumbBackgroundColor. Returns None on failure so the caller can
	fall back to normal serving."""
	try:
		# RAW must be decoded by dcraw first; everything else PIL opens directly
		if ext in fs.RAW_EXTS:
			raw = fs.dcraw_extract(server_path)
			if not raw:
				return None
			src = Image.open(io.BytesIO(raw))
		else:
			src = Image.open(server_path)

		with src as img:
			img = ImageOps.exif_transpose(img)  # type: ignore
			has_alpha = img.mode in ('RGBA', 'LA', 'PA') or \
				(img.mode == 'P' and 'transparency' in img.info)
			if has_alpha:
				rgba   = img.convert('RGBA')
				canvas = Image.new('RGB', rgba.size, ImageColor.getrgb(config('thumbBackgroundColor')))
				canvas.paste(rgba, (0, 0), rgba)  # rgba alpha as its own mask
			else:
				canvas = img.convert('RGB')

			buf = io.BytesIO()
			canvas.save(buf, format='JPEG',
						quality=config_get('slowClientJpegQuality', 50), optimize=True)
			return buf.getvalue(), 'image/jpeg', None, None, None
	except Exception:
		log(f'handle_file slow jpeg: {traceback.format_exc()}')
		return None
