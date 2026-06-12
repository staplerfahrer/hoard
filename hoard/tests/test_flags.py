import os

import pytest

import flags
import handle_flag


# ── storage round-trip ───────────────────────────────────────────────────────

def test_set_and_read_flag(tmp_path):
	f = tmp_path / 'a.jpg'
	flags.set_flag(str(f), 'pick')
	assert flags.read_flags(str(tmp_path)) == {'a.jpg': 'pick'}


def test_missing_dir_reads_empty(tmp_path):
	assert flags.read_flags(str(tmp_path)) == {}


def test_notes_file_is_readable_yaml(tmp_path):
	flags.set_flag(str(tmp_path / 'a.jpg'), 'reject')
	notes = tmp_path / flags.NOTES_FILE
	assert notes.is_file()
	text = notes.read_text(encoding='utf-8')
	assert text.startswith('#')        # human-readable warning header
	assert 'flags:' in text
	assert 'a.jpg: reject' in text     # bare (unambiguous) filename


def test_quotes_ambiguous_filename_and_round_trips(tmp_path):
	# '#' would start a YAML comment unquoted, so it must be quoted on emit
	name = 'holiday #2 (best).jpg'
	flags.set_flag(str(tmp_path / name), 'pick')
	assert f'"{name}": pick' in (tmp_path / flags.NOTES_FILE).read_text(encoding='utf-8')
	assert flags.read_flags(str(tmp_path)) == {name: 'pick'}


def test_none_clears_entry_and_removes_empty_file(tmp_path):
	f = tmp_path / 'a.jpg'
	flags.set_flag(str(f), 'pick')
	flags.set_flag(str(f), 'none')
	assert flags.read_flags(str(tmp_path)) == {}
	assert not (tmp_path / flags.NOTES_FILE).exists()  # emptied → removed


def test_clearing_one_keeps_others(tmp_path):
	flags.set_flag(str(tmp_path / 'a.jpg'), 'pick')
	flags.set_flag(str(tmp_path / 'b.jpg'), 'reject')
	flags.set_flag(str(tmp_path / 'a.jpg'), 'none')
	assert flags.read_flags(str(tmp_path)) == {'b.jpg': 'reject'}
	assert (tmp_path / flags.NOTES_FILE).is_file()     # still has an entry


def test_bad_state_raises(tmp_path):
	with pytest.raises(ValueError):
		flags.set_flag(str(tmp_path / 'a.jpg'), 'bogus')


# ── packed-char mapping (mirrors gallery.js FLAG_* codes) ─────────────────────

@pytest.mark.parametrize('state, char', [
	('pick',   'p'),
	('reject', 'r'),
	('none',   'n'),
])
def test_flag_char(state, char):
	dir_flags = {'a.jpg': state} if state != 'none' else {}
	assert flags.flag_char(dir_flags, 'a.jpg') == char


def test_flag_char_unknown_file_is_none():
	assert flags.flag_char({}, 'missing.jpg') == 'n'


# ── favorites (independent of the pick/reject flag) ──────────────────────────

def test_set_and_read_favorite(tmp_path):
	flags.set_favorite(str(tmp_path / 'a.jpg'), True)
	assert flags.read_favorites(str(tmp_path)) == ['a.jpg']
	text = (tmp_path / flags.NOTES_FILE).read_text(encoding='utf-8')
	assert 'favorites:' in text and '- a.jpg' in text


def test_favorite_is_independent_of_flag(tmp_path):
	# a file can be both a pick and a favorite, and changing one keeps the other
	f = str(tmp_path / 'a.jpg')
	flags.set_flag(f, 'pick')
	flags.set_favorite(f, True)
	assert flags.read_flags(str(tmp_path)) == {'a.jpg': 'pick'}
	assert flags.read_favorites(str(tmp_path)) == ['a.jpg']
	flags.set_flag(f, 'none')                     # clear the flag…
	assert flags.read_favorites(str(tmp_path)) == ['a.jpg']   # …favorite survives
	flags.set_favorite(f, False)                  # clear the favorite…
	assert flags.read_flags(str(tmp_path)) == {}  # …nothing left → file gone
	assert not (tmp_path / flags.NOTES_FILE).exists()


def test_favorite_off_removes_only_that_file(tmp_path):
	flags.set_favorite(str(tmp_path / 'a.jpg'), True)
	flags.set_favorite(str(tmp_path / 'b.jpg'), True)
	flags.set_favorite(str(tmp_path / 'a.jpg'), False)
	assert flags.read_favorites(str(tmp_path)) == ['b.jpg']


def test_favorite_char():
	assert flags.favorite_char({'a.jpg'}, 'a.jpg') == '1'
	assert flags.favorite_char({'a.jpg'}, 'b.jpg') == '0'


def test_favorite_handler_toggles(tmp_path):
	f = tmp_path / 'a.jpg'
	assert handle_flag.run_favorite(f'{f}?fav=on') == (b'ok', 'text/plain')
	assert flags.read_favorites(str(tmp_path)) == ['a.jpg']
	handle_flag.run_favorite(f'{f}?fav=off')
	assert flags.read_favorites(str(tmp_path)) == []


# ── handler endpoint (GET <file>?flag=<state>) ───────────────────────────────

def test_handler_persists_flag(tmp_path):
	f = tmp_path / 'a.jpg'
	data, mime = handle_flag.run(f'{f}?flag=pick')
	assert (data, mime) == (b'ok', 'text/plain')
	assert flags.read_flags(str(tmp_path)) == {'a.jpg': 'pick'}


def test_handler_rejects_bad_state(tmp_path):
	data, _ = handle_flag.run(f'{tmp_path / "a.jpg"}?flag=bogus')
	assert data == b'bad state'
