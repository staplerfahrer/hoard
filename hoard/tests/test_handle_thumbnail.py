from PIL import Image

import handle_thumbnail as ht


def test_run_returns_dimensions(tmp_path):
	p = tmp_path / 'pic.jpg'
	Image.new('RGB', (1234, 567), (100, 150, 200)).save(p)
	data, mime, dims = ht.run(str(p) + '?tn')
	assert mime == 'image/jpeg'
	assert dims == '1234 x 567'
	assert data[:2] == b'\xff\xd8'   # JPEG SOI


def test_run_unreadable_file_reports_cannot_render(tmp_path):
	p = tmp_path / 'broken.jpg'
	p.write_text('not an image')
	data, mime, dims = ht.run(str(p) + '?tn')
	assert mime == 'image/jpeg'
	assert dims == 'cannot render'
	assert data[:2] == b'\xff\xd8'   # still a JPEG (the error icon)
