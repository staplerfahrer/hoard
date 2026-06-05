"""Handle a file flag change: GET <file>?flag=<pick|reject|none>.

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
