"""Per-file pick/reject flags, persisted in a human-friendly notes.txt per dir.

Each directory with flagged files gets a `notes.txt` holding a YAML `flags:` map
of {filename: state}. The file is created on demand and removed once it holds
nothing. States: 'pick', 'reject' (persisted), 'none' (entry removed).
`handle_directory` packs each file's state one char per file ('p'/'r'/'n') into
the gallery bootstrap, mirroring the kinds string, so the viewer shows flag state
without extra requests.

The file is plain YAML (emitted/parsed here, no library) so it stays readable; a
comment header warns that hoard manages it. Filenames are emitted bare when they
are unambiguous plain scalars, else double-quoted.
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
	'# hoard notes — pick / reject marks for the files in this folder.\n'
	'#\n'
	'# hoard manages this file: it is rewritten whenever you change a flag in the\n'
	'# viewer (the "p" key), so hand edits to the "flags" section may be overwritten.\n'
	'# Filenames must match exactly. Deleting this file clears the folder\'s flags.\n'
	'\n'
)

_lock = threading.Lock()


def _notes_path(directory: str) -> str:
	return os.path.join(directory, NOTES_FILE)


def read_flags(directory: str) -> dict[str, str]:
	"""Map of {filename: state} from a directory's notes.txt ({} if none)."""
	try:
		with open(_notes_path(directory), 'r', encoding='utf-8') as f:
			lines = f.read().splitlines()
	except FileNotFoundError:
		return {}
	except Exception:
		log(f'notes read failed for {directory}: {traceback.format_exc()}')
		return {}

	flags: dict[str, str] = {}
	in_flags = False
	for line in lines:
		stripped = line.strip()
		if not in_flags:
			if stripped == 'flags:':
				in_flags = True
			continue
		if stripped == '' or stripped.startswith('#'):
			continue
		if not line[:1].isspace():   # an un-indented key ends the flags block
			break
		parsed = _parse_entry(stripped)
		if parsed and parsed[1] in ('pick', 'reject'):
			flags[parsed[0]] = parsed[1]
	return flags


def flag_char(directory_flags: dict[str, str], filename: str) -> str:
	"""Packed one-char state ('p'/'r'/'n') for a file given its dir's flag map."""
	return _CHAR.get(directory_flags.get(filename, 'none'), 'n')


def set_flag(file_path: str, state: str) -> None:
	"""Persist a file's flag in its directory's notes.txt.

	'none' clears the entry; a notes.txt left holding nothing is removed.
	"""
	if state not in STATES:
		raise ValueError(f'bad flag state: {state!r}')
	directory = os.path.dirname(file_path)
	filename  = os.path.basename(file_path)
	with _lock:
		flags = read_flags(directory)
		if state == 'none':
			flags.pop(filename, None)
		else:
			flags[filename] = state
		_write(directory, flags)


def _write(directory: str, flags: dict[str, str]) -> None:
	path = _notes_path(directory)
	if not flags:                    # nothing left to record — drop the file
		if os.path.isfile(path):
			os.remove(path)
		return
	body = ['flags:\n']
	body += [f'  {_emit_key(name)}: {state}\n' for name, state in flags.items()]
	with open(path, 'w', encoding='utf-8') as f:
		f.write(_HEADER + ''.join(body))


# ── tiny YAML emit/parse for the restricted {filename: state} schema ──────────

# unambiguous plain scalar: starts alnum/_ and has no YAML-significant ':' or '#'
_PLAIN = re.compile(r'^[A-Za-z0-9_][^:#\t\n]*$')


def _emit_key(name: str) -> str:
	if name and name == name.strip() and _PLAIN.match(name):
		return name
	return '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _parse_entry(stripped: str) -> tuple[str, str] | None:
	"""Parse one 'key: value' flags line (key bare or double-quoted)."""
	if stripped.startswith('"'):
		i, buf = 1, []
		while i < len(stripped):
			c = stripped[i]
			if c == '\\' and i + 1 < len(stripped):
				buf.append(stripped[i + 1])
				i += 2
				continue
			if c == '"':
				break
			buf.append(c)
			i += 1
		rest = stripped[i + 1:].lstrip()
		if not rest.startswith(':'):
			return None
		return ''.join(buf), rest[1:].strip()
	if ':' not in stripped:
		return None
	key, _, val = stripped.rpartition(':')
	return key.strip(), val.strip()
