import io
import os
# pip install types-Pillow to fix Pylance
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps, ImageFilter
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
		tnWidthHeight = config('thumbnailWidthHeight')
		tnColor = config('thumbBackgroundColor')
		reqObj  = serverPath[:-3]
		file_name = os.path.split(reqObj)[-1:][0]
		file_extension = os.path.splitext(reqObj)[1][1:].upper()

		reqObjBytes: io.BytesIO | None      = None
		reqObjImage: Image.Image | None     = None

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

		# make a thumbnail
		try:
			if reqObjImage:
				img = reqObjImage # type: ignore
			elif reqObjBytes:
				img = Image.open(reqObjBytes)
			else:
				img  = Image.open(reqObj)
			img  = ImageOps.exif_transpose(img) # type: ignore
			text = f'{file_extension}  {img.size[0]} x {img.size[1]}'

			# convert to RGB
			if img.mode in ['P', 'CMYK']:
				img = img.convert('RGB')
			if img.mode in ['PA', 'LA']:
				img = img.convert('RGBA')
			has_alpha = img.mode in ('RGBA', 'LA', 'PA') or \
				(img.mode == 'P' and 'transparency' in img.info)

			# generate thumbnail
			# https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.thumbnail
			img.thumbnail(size=tnWidthHeight, resample=Image.Resampling.LANCZOS, reducing_gap=1.0)
			img = img.filter(ImageFilter.UnsharpMask(radius=6, percent=20))

			canvas = Image.new(img.mode, tnWidthHeight, tnColor if img.mode == 'RGB' else 0)
			left   = (tnWidthHeight[0] - img.size[0]) // 2
			top    = (tnWidthHeight[1] - img.size[1]) // 2
			canvas.paste(img, (left, top))
			draw   = ImageDraw.Draw(canvas)
			font   = ImageFont.load_default()
			text_box = draw.textbbox((0, 0), text, font=font)
			tw, th = text_box[2] - text_box[0], text_box[3] - text_box[1]
			font_color = (95, 95, 95) if canvas.mode in ('RGB', 'RGBA') else 95
			draw.text((tnWidthHeight[0] - tw - 2, tnWidthHeight[1] - th - 5), text, font=font, fill=font_color) # pyright: ignore[reportUnknownMemberType]

			# sharpen
			canvas = ImageEnhance.Sharpness(canvas).enhance(factor=SHARPEN)
		except Exception:
			log(f'Exception at "make a thumbnail": {traceback.format_exc()}')
			reqObj = os.path.join('resources', 'Enso.png')
			has_alpha = True
			img  = Image.open(reqObj)
			text = f'BAD FILE  {file_name}'

			img.thumbnail(size=tnWidthHeight)

			canvas = Image.new(img.mode, tnWidthHeight, 0)
			left   = (tnWidthHeight[0] - img.size[0]) // 2
			top    = (tnWidthHeight[1] - img.size[1]) // 2
			canvas.paste(img, (left, top))
			draw   = ImageDraw.Draw(canvas)
			font   = ImageFont.load_default()
			text_box = draw.textbbox((0, 0), text, font=font)
			tw, th = text_box[2] - text_box[0], text_box[3] - text_box[1]
			font_color = (95, 95, 95) if canvas.mode in ('RGB', 'RGBA') else 95
			draw.text((tnWidthHeight[0] - tw - 2, tnWidthHeight[1] - th - 5), text, font=font, fill=font_color) # pyright: ignore[reportUnknownMemberType]

		buf = io.BytesIO()
		if has_alpha:
			canvas.save(buf, format='png', optimize=False, compress_level=9)
			log('returning png')
			result: tuple[bytes, str] = (buf.getvalue(), 'image/png')
		else:
			canvas.save(buf, format='jpeg', quality=90, optimize=False, progressive=True, subsampling=1)
			log('returning jpeg')
			result = (buf.getvalue(), 'image/jpeg')

		elapsed = time.perf_counter() - t0
		if elapsed > _SLOW_THRESHOLD:
			with _lock:
				_last_slow_at = time.monotonic()
			log(f'handle_thumbnail slow: {elapsed:.3f}s')

		return result
	finally:
		with _lock:
			_active_count -= 1

