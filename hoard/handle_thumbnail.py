import io
import os
# pip install types-Pillow to fix Pylance
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps, ImageFilter, ImageColor
import av
import threading
import time
import traceback

from config import config
import filesystem as fs
from log import log


SHARPEN = 1.3

_lock                = threading.Lock()
_active_count: int   = 0
_last_slow_at: float = 0.0
_MAX_CONCURRENT      = 30
_SLOW_MAX_CONCURRENT = 10
_SLOW_THRESHOLD      = 10.0
_SLOW_COOLDOWN       = 10.0


def run(serverPath: str) -> tuple[bytes, str] | None:
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
		log(f'handle_thumbnail {serverPath}')
		tnWidthHeight  = config('thumbnailWidthHeight')
		tnColor        = ImageColor.getrgb(config('thumbBackgroundColor'))
		reqObj         = serverPath[:-3]
		file_name      = os.path.split(reqObj)[-1:][0]

		reqObjBytes: io.BytesIO | None  = None
		reqObjImage: Image.Image | None = None

		# if video, extract a frame via PyAV (in-process, no subprocess)
		try:
			if not (reqObj.endswith('.mp4') or reqObj.endswith('.m4v') or reqObj.endswith('.mov') or reqObj.endswith('.ts')):
				raise Exception('not a video')
			timeStamps = config('videoThumbnailTimeStamps')
			with av.open(reqObj) as container:
				stream = container.streams.video[0]
				stream.codec_context.skip_frame = 'NONKEY'
				for ts in timeStamps:
					h, m, s = ts.split(':')
					seek_us = int((int(h) * 3600 + int(m) * 60 + float(s)) * 1_000_000)
					try:
						container.seek(seek_us)
						for frame in container.decode(stream):
							reqObjImage = frame.to_image() # type: ignore
							break
					except Exception:
						continue
					if reqObjImage:
						break
		except Exception as e:
			if 'not a video' not in e.args:
				log(f'Exception at "video thumbnail": {traceback.format_exc()}')

		# for RAW files, extract the embedded JPEG via dcraw before PIL opens it
		if not reqObjImage:
			raw_ext = os.path.splitext(reqObj)[1].lower()
			if raw_ext in fs.RAW_EXTS:
				raw_bytes = fs.dcraw_extract(reqObj)
				if raw_bytes:
					reqObjBytes = io.BytesIO(raw_bytes)

		# for PDF files, render page 0 via PyMuPDF
		pdf_page_count: int | None = None
		if not reqObjImage and reqObj.lower().endswith('.pdf'):
			try:
				import fitz  # PyMuPDF
				doc = fitz.open(reqObj)
				pdf_page_count = len(doc)
				pix = doc[0].get_pixmap(matrix=fitz.Matrix(2.0, 2.0), colorspace=fitz.csRGB) # type: ignore
				reqObjImage = Image.frombytes('RGB', (pix.width, pix.height), pix.samples) # type: ignore
				doc.close()
			except Exception:
				log(f'Exception at "pdf thumbnail": {traceback.format_exc()}')

		# make a thumbnail
		font = ImageFont.load_default(size=12)
		try:
			if reqObjImage:
				img = reqObjImage # type: ignore
			elif reqObjBytes:
				img = Image.open(reqObjBytes)
			else:
				img = Image.open(reqObj)
			img = ImageOps.exif_transpose(img) # type: ignore
			if img.mode != 'RGB':
				img = img.convert('RGB')

			text_right = f'{pdf_page_count} page{"" if pdf_page_count == 1 else "s"}' if pdf_page_count is not None else f'{img.size[0]} x {img.size[1]}'

			# generate thumbnail
			# https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.thumbnail
			img.thumbnail(size=tnWidthHeight, resample=Image.Resampling.LANCZOS, reducing_gap=1.0)
			img = img.filter(ImageFilter.UnsharpMask(radius=6, percent=20))

			canvas = Image.new('RGB', tnWidthHeight, tnColor)
			paste_centered(canvas, img)

			draw       = ImageDraw.Draw(canvas, 'RGBA')
			draw_label(draw, tnWidthHeight, font, tnColor, file_name,  'left')
			draw_label(draw, tnWidthHeight, font, tnColor, text_right, 'right')

			# sharpen
			canvas = ImageEnhance.Sharpness(canvas).enhance(factor=SHARPEN)
		except Exception:
			log(f'Exception at "make a thumbnail": {traceback.format_exc()}')
			icon = Image.open(os.path.join('resources', 'Enso.png'))
			icon.thumbnail(size=tnWidthHeight)

			canvas = Image.new('RGB', tnWidthHeight, tnColor)
			paste_centered(canvas, icon, icon if icon.mode == 'RGBA' else None)

			draw = ImageDraw.Draw(canvas, 'RGBA')
			draw_label(draw, tnWidthHeight, font, tnColor, f'Can\'t render {file_name}', 'left')

		buf = io.BytesIO()
		canvas.save(buf, format='jpeg', quality=95, optimize=False, progressive=True, subsampling=1)
		log('returning jpeg')
		result: tuple[bytes, str] = (buf.getvalue(), 'image/jpeg')

		elapsed = time.perf_counter() - t0
		if elapsed > _SLOW_THRESHOLD:
			with _lock:
				_last_slow_at = time.monotonic()
			log(f'handle_thumbnail slow: {elapsed:.3f}s')

		return result
	finally:
		with _lock:
			_active_count -= 1

FONT_COLOR   = (191, 191, 191, 255)
SHADOW_COLOR = (0, 0, 0, 255)
TEXT_MARGIN  = 5

def paste_centered(canvas: Image.Image, img: Image.Image, mask: Image.Image | None = None):
	x = (canvas.size[0] - img.size[0]) // 2
	y = (canvas.size[1] - img.size[1]) // 2
	canvas.paste(img, (x, y), mask)

def draw_label(draw: ImageDraw.ImageDraw, canvasSize: tuple[int, int],
			   font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
			   bgColor: tuple[int, int, int], text: str, align: str):
	w, h = canvasSize
	bb   = draw.textbbox((0, 0), text, font=font)
	tw   = bb[2] - bb[0]
	y    = h - 18
	box  = bgColor + (90,)
	if align == 'right':
		x = w - tw - TEXT_MARGIN
		draw.rectangle((w - tw - TEXT_MARGIN - 2, y - 1, w, h), fill=box)
	else:
		x = TEXT_MARGIN
		draw.rectangle((0, y - 1, x + tw + 2, h), fill=box)
	text_outline(draw, x, y, text, font, SHADOW_COLOR)
	draw.text((x, y), text, font=font, fill=FONT_COLOR)

def text_outline(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
				 font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
				 color: tuple[int, int, int, int]):
	for y1 in range(-1, 2):
		for x1 in range(-1, 2):
			draw.text((x+x1, y+y1), text,  font=font, fill=color)
