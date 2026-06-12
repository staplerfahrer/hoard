"""Per-file pick/reject flags and favorites, persisted in a human-friendly
notes.txt per directory.

Each directory with marked files gets a `notes.txt` holding a YAML `flags:` map of
{filename: state} and/or a `favorites:` list of filenames. The file is created on
demand and removed once it holds nothing. Flag states: 'pick', 'reject' (persisted),
'none' (entry removed). Favorite is an INDEPENDENT toggle — a file can be both a
pick and a favorite. `handle_directory` packs each file's flag state ('p'/'r'/'n')
and favorite bit ('1'/'0') one char per file into the gallery bootstrap, mirroring
the kinds string, so the viewer shows state without extra requests.

The file is plain YAML (emitted/parsed here, no library) so it stays readable; a
comment header warns that hoard manages it. Names are emitted bare when they are
unambiguous plain scalars, else double-quoted.
"""
import os
import re
import threading
import traceback

from log import log

NOTES_FILE = 'notes.txt'
STATES     = ('pick', 'reject', 'none')
_CHAR      = {'pick': 'p', 'reject': 'r', 'none': 'n'}

# Prepended on every write — guidance for anyone who opens notes.txt by hand.
_HEADER = (
	'# hoard notes — pick / reject marks and favorites for the files in this folder.\n'
	'#\n'
	'# hoard manages this file: it is rewritten whenever you change a flag or favorite\n'
	'# in the viewer, so hand edits to the "flags"/"favorites" sections may be lost.\n'
	'# Filenames must match exactly. Deleting this file clears the folder\'s marks.\n'
	'\n'
)

_lock = threading.Lock()


def _notes_path(directory: str) -> str:
	return os.path.join(directory, NOTES_FILE)


def _read(directory: str) -> tuple[dict[str, str], list[str]]:
	"""Parse notes.txt → ({filename: state}, [favorite filenames]); empty if absent."""
	try:
		with open(_notes_path(directory), 'r', encoding='utf-8') as f:
			lines = f.read().splitlines()
	except FileNotFoundError:
		return {}, []
	except Exception:
		log(f'notes read failed for {directory}: {traceback.format_exc()}')
		return {}, []

	flags: dict[str, str] = {}
	favorites: list[str]  = []
	section = None
	for line in lines:
		stripped = line.strip()
		if stripped == '' or stripped.startswith('#'):
			continue
		if not line[:1].isspace():                 # un-indented → a top-level key
			section = stripped[:-1] if stripped.endswith(':') else None
			continue
		if section == 'flags':
			parsed = _parse_entry(stripped)
			if parsed and parsed[1] in ('pick', 'reject'):
				flags[parsed[0]] = parsed[1]
		elif section == 'favorites':
			if stripped.startswith('-'):
				name = _parse_scalar(stripped[1:].strip())
				if name:
					favorites.append(name)
	return flags, favorites


def read_flags(directory: str) -> dict[str, str]:
	"""Map of {filename: state} from a directory's notes.txt ({} if none)."""
	return _read(directory)[0]


def read_favorites(directory: str) -> list[str]:
	"""List of favorited filenames from a directory's notes.txt ([] if none)."""
	return _read(directory)[1]


def flag_char(directory_flags: dict[str, str], filename: str) -> str:
	"""Packed one-char flag state ('p'/'r'/'n') for a file."""
	return _CHAR.get(directory_flags.get(filename, 'none'), 'n')


def favorite_char(directory_favorites, filename: str) -> str:
	"""Packed one-char favorite bit ('1' favorite, else '0') for a file."""
	return '1' if filename in directory_favorites else '0'


def set_flag(file_path: str, state: str) -> None:
	"""Persist a file's pick/reject flag. 'none' clears it; favorites are preserved."""
	if state not in STATES:
		raise ValueError(f'bad flag state: {state!r}')
	directory = os.path.dirname(file_path)
	filename  = os.path.basename(file_path)
	with _lock:
		flags, favorites = _read(directory)
		if state == 'none':
			flags.pop(filename, None)
		else:
			flags[filename] = state
		_write(directory, flags, favorites)


def set_favorite(file_path: str, on: bool) -> None:
	"""Add or remove a file from its directory's favorites; flags are preserved."""
	directory = os.path.dirname(file_path)
	filename  = os.path.basename(file_path)
	with _lock:
		flags, favorites = _read(directory)
		if on:
			if filename not in favorites:
				favorites.append(filename)
		else:
			favorites = [f for f in favorites if f != filename]
		_write(directory, flags, favorites)


def _write(directory: str, flags: dict[str, str], favorites: list[str]) -> None:
	path = _notes_path(directory)
	if not flags and not favorites:      # nothing left to record — drop the file
		if os.path.isfile(path):
			os.remove(path)
		return
	body: list[str] = []
	if flags:
		body.append('flags:\n')
		body += [f'  {_emit_key(name)}: {state}\n' for name, state in flags.items()]
	if favorites:
		body.append('favorites:\n')
		body += [f'  - {_emit_key(name)}\n' for name in favorites]
	with open(path, 'w', encoding='utf-8') as f:
		f.write(_HEADER + ''.join(body))


# ── tiny YAML emit/parse for the restricted schema ───────────────────────────

# unambiguous plain scalar: starts alnum/_ and has no YAML-significant ':' or '#'
_PLAIN = re.compile(r'^[A-Za-z0-9_][^:#\t\n]*$')


def _emit_key(name: str) -> str:
	if name and name == name.strip() and _PLAIN.match(name):
		return name
	return '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _parse_scalar(s: str) -> str:
	"""Parse a bare or double-quoted YAML scalar."""
	if s.startswith('"'):
		i, buf = 1, []
		while i < len(s):
			c = s[i]
			if c == '\\' and i + 1 < len(s):
				buf.append(s[i + 1]); i += 2; continue
			if c == '"':
				break
			buf.append(c); i += 1
		return ''.join(buf)
	return s.strip()


def _parse_entry(stripped: str) -> tuple[str, str] | None:
	"""Parse one 'key: value' flags line (key bare or double-quoted)."""
	if stripped.startswith('"'):
		i, buf = 1, []
		while i < len(stripped):
			c = stripped[i]
			if c == '\\' and i + 1 < len(stripped):
				buf.append(stripped[i + 1]); i += 2; continue
			if c == '"':
				break
			buf.append(c); i += 1
		rest = stripped[i + 1:].lstrip()
		if not rest.startswith(':'):
			return None
		return ''.join(buf), rest[1:].strip()
	if ':' not in stripped:
		return None
	key, _, val = stripped.rpartition(':')
	return key.strip(), val.strip()
