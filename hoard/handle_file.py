import io
import os
import traceback
from PIL import Image
import filesystem as fs
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

def run(server_path: str, range_l: int | None, range_u: int | None) \
		-> tuple[bytes, str, int | None, int | None, int | None] | None:
	if not os.path.isfile(server_path):
		return None

	# convert raw files
	ext = os.path.splitext(server_path)[1].lower()
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
	mime = _pil_mime(server_path, mime)
	return data, mime, range_l, range_u, end


def _pil_mime(server_path: str, fallback: str) -> str:
	try:
		with Image.open(server_path) as img:
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
