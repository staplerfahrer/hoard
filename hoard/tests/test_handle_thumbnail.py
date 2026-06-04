from PIL import Image, ImageDraw, ImageFont

import handle_thumbnail as ht


def _draw():
	img  = Image.new('RGB', (10, 10))
	font = ImageFont.load_default(size=12)
	return ImageDraw.Draw(img), font


def test_ellipsize_leaves_short_text_unchanged():
	draw, font = _draw()
	assert ht.ellipsize(draw, 'short.jpg', font, 1000) == 'short.jpg'


def test_ellipsize_truncates_and_fits():
	draw, font = _draw()
	long_name = 'an_extremely_long_filename_that_will_never_fit.jpg'
	out = ht.ellipsize(draw, long_name, font, 60)
	assert out.endswith('…')
	assert out != long_name
	assert draw.textlength(out, font=font) <= 60


def test_ellipsize_zero_width_returns_empty():
	draw, font = _draw()
	assert ht.ellipsize(draw, 'anything', font, 0) == ''


def test_ellipsize_negative_width_returns_empty():
	draw, font = _draw()
	assert ht.ellipsize(draw, 'anything', font, -5) == ''
