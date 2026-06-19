import io
import os
# pip install types-Pillow to fix Pylance
from PIL import Image, ImageEnhance, ImageOps, ImageFilter, ImageColor, UnidentifiedImageError
import av
import threading
import time
import traceback

from config import config
import filesystem as fs
import plugins
from log import log


SHARPEN = 1.3

_lock                = threading.Lock()
_active_count: int   = 0
_last_slow_at: float = 0.0
_MAX_CONCURRENT      = 30  # mirrors main.THREAD_COUNT (not imported — would be circular)
_SLOW_MAX_CONCURRENT = 10
_SLOW_THRESHOLD      = 10.0
_SLOW_COOLDOWN       = 10.0

_error_icon: Image.Image | None = None


def _error_icon_copy() -> Image.Image:
	"""The 'cannot render' icon, loaded from disk once and cached. Returns a fresh
	RGBA copy each call so the caller can thumbnail/mutate it freely."""
	global _error_icon
	if _error_icon is None:
		_error_icon = Image.open(os.path.join('resources', 'Enso.png')).convert('RGBA')
	return _error_icon.copy()


def run(server_path: str) -> tuple[bytes, str, str] | None:
	global _active_count, _last_slow_at

	with _lock:
		is_slow_mode = (time.monotonic() - _last_slow_at) < _SLOW_COOLDOWN
		limit = _SLOW_MAX_CONCURRENT if is_slow_mode else _MAX_CONCURRENT
		if _active_count >= limit:
			log(f'handle_thumbnail throttled (active={_active_count}, slow_mode={is_slow_mode})')
			return None
		_active_count += 1

	t0 = time.perf_counter()
	try:
		log(f'handle_thumbnail {server_path}')
		tn_size   = config('thumbnailWidthHeight')
		tn_color  = ImageColor.getrgb(config('thumbBackgroundColor'))
		req_obj   = server_path[:-3]
		ext       = os.path.splitext(req_obj)[1].lower()

		req_obj_bytes: io.BytesIO | None  = None
		req_obj_image: Image.Image | None = None

		# render plugins take precedence; their preview rides the pipeline below
		plugin = plugins.plugin_for(req_obj)
		if plugin is not None:
			try:
				req_obj_bytes = io.BytesIO(plugin.render_thumbnail(req_obj, tn_size))
			except Exception:
				log(f'plugin thumbnail failed for {req_obj}: {traceback.format_exc()}')

		# if video, extract a frame via PyAV (in-process, no subprocess)
		if req_obj_bytes is None and ext in fs.VIDEO_EXTS:
			try:
				time_stamps = config('videoThumbnailTimeStamps')
				with av.open(req_obj) as container:
					stream = container.streams.video[0]
					stream.codec_context.skip_frame = 'NONKEY'
					for ts in time_stamps:
						h, m, s = ts.split(':')
						seek_us = int((int(h) * 3600 + int(m) * 60 + float(s)) * 1_000_000)
						try:
							container.seek(seek_us)
							for frame in container.decode(stream):
								req_obj_image = frame.to_image() # type: ignore
								break
						except Exception:
							continue
						if req_obj_image:
							break
			except Exception:
				log(f'Exception at "video thumbnail": {traceback.format_exc()}')

		# for RAW files, extract the embedded JPEG via dcraw before PIL opens it
		if not req_obj_image and req_obj_bytes is None and ext in fs.RAW_EXTS:
			raw_bytes = fs.dcraw_extract(req_obj)
			if raw_bytes:
				req_obj_bytes = io.BytesIO(raw_bytes)

		# for PDF files, render page 0 via PyMuPDF
		pdf_page_count: int | None = None
		if not req_obj_image and req_obj_bytes is None and ext == '.pdf':
			try:
				import fitz  # PyMuPDF
				doc = fitz.open(req_obj)
				pdf_page_count = len(doc)
				pix = doc[0].get_pixmap(matrix=fitz.Matrix(2.0, 2.0), colorspace=fitz.csRGB) # type: ignore
				req_obj_image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples) # type: ignore
				doc.close()
			except Exception:
				log(f'Exception at "pdf thumbnail": {traceback.format_exc()}')

		# make a thumbnail. The filename/dimension labels are no longer baked into
		# the pixels — the dimension string is returned and emitted as the
		# X-Thumb-Dims header, so the client renders it (and the filename) as HTML.
		try:
			if req_obj_image:
				img = req_obj_image # type: ignore
			elif req_obj_bytes:
				img = Image.open(req_obj_bytes)
			else:
				img = Image.open(req_obj)
			img = ImageOps.exif_transpose(img) # type: ignore
			if img.mode != 'RGBA':
				img = img.convert('RGBA')

			# original-resolution label (computed before thumbnail() shrinks img)
			dims = f'{pdf_page_count} page{"" if pdf_page_count == 1 else "s"}' if pdf_page_count is not None else f'{img.size[0]} x {img.size[1]}'

			# generate thumbnail
			# https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.thumbnail
			img.thumbnail(size=tn_size, resample=Image.Resampling.LANCZOS, reducing_gap=1.0)
			img = img.filter(ImageFilter.UnsharpMask(radius=6, percent=20))

			canvas = Image.new('RGB', tn_size, tn_color)
			paste_centered(canvas, img)

			# sharpen
			canvas = ImageEnhance.Sharpness(canvas).enhance(factor=SHARPEN)
		except Exception as e:
			log(f'{server_path} exception at "make a thumbnail":\n'
				f'{traceback.format_exc()}')
			icon = _error_icon_copy()
			icon.thumbnail(size=tn_size)

			canvas = Image.new('RGB', tn_size, tn_color)
			paste_centered(canvas, icon, icon)
			dims = 'cannot render'

		buf = io.BytesIO()
		canvas.save(buf, format='jpeg', quality=98, optimize=False, progressive=False, subsampling=1)
		log('returning jpeg')
		result: tuple[bytes, str, str] = (buf.getvalue(), 'image/jpeg', dims)

		elapsed = time.perf_counter() - t0
		if elapsed > _SLOW_THRESHOLD:
			with _lock:
				_last_slow_at = time.monotonic()
			log(f'handle_thumbnail slow: {elapsed:.3f}s')

		return result
	finally:
		with _lock:
			_active_count -= 1

def paste_centered(canvas: Image.Image, img: Image.Image, mask: Image.Image | None = None):
	x = (canvas.size[0] - img.size[0]) // 2
	y = (canvas.size[1] - img.size[1]) // 2
	canvas.paste(img, (x, y), mask)
