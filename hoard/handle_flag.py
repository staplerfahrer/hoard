"""Handle file mark changes:
    GET <file>?flag=<pick|reject|none>   pick/reject/none flag
    GET <file>?fav=<on|off>              favorite toggle (independent of the flag)
    GET <file>?rotate=<0|90|180|270>     viewer rotation in degrees (independent)

Stateless like the other handlers; persistence lives in flags.py.
"""
import traceback

from log import log
import flags


def run(server_path: str) -> tuple[bytes, str]:
	path, _, state = server_path.partition('?flag=')
	try:
		flags.set_flag(path, state)
		return b'ok', 'text/plain'
	except ValueError:
		return b'bad state', 'text/plain'
	except Exception:
		log(f'flag failed: {traceback.format_exc()}')
		return b'error', 'text/plain'


def run_favorite(server_path: str) -> tuple[bytes, str]:
	path, _, val = server_path.partition('?fav=')
	try:
		flags.set_favorite(path, val == 'on')
		return b'ok', 'text/plain'
	except Exception:
		log(f'favorite failed: {traceback.format_exc()}')
		return b'error', 'text/plain'


def run_rotation(server_path: str) -> tuple[bytes, str]:
	path, _, val = server_path.partition('?rotate=')
	try:
		flags.set_rotation(path, int(val))
		return b'ok', 'text/plain'
	except ValueError:
		return b'bad rotation', 'text/plain'
	except Exception:
		log(f'rotation failed: {traceback.format_exc()}')
		return b'error', 'text/plain'
