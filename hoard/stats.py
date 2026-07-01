import threading
import time

from config import config_get

lock:             threading.Lock = threading.Lock()
thumbnails_served: int            = 0
bytes_served:      int            = 0
processing_time:   float          = 0.0
requests_served:   int            = 0

# Per-client connection state, keyed by client IP. A client is judged "slow" when a
# big-enough response is sent below a throughput threshold; once slow it stays slow for
# slowClientHours, during which its images/thumbnails are served as low-quality JPEGs.
#   ip -> {'last_seen': float, 'slow_until': float}   (both are time.time() epochs)
clients: dict[str, dict] = {}


def is_slow(ip: str) -> bool:
	"""True if this client is currently within its slow-connection window."""
	now = time.time()
	with lock:
		c = clients.get(ip)
		return bool(c and c['slow_until'] > now)


def note_request(ip: str, nbytes: int, send_dt: float, is_thumb: bool) -> bool:
	"""Record a completed send to `ip` and, when the transfer was big enough to judge
	and slower than the throughput threshold, mark the client slow for slowClientHours.
	Returns True only on the transition into slow (so the caller can log it once)."""
	now          = time.time()
	sample_bytes = config_get('slowClientSampleBytes', 262144)
	min_bps      = config_get('slowClientMinBytesPerSec', 1_000_000)
	hours        = config_get('slowClientHours', 2)
	with lock:
		c = clients.setdefault(ip, {'last_seen': 0.0, 'slow_until': 0.0})
		c['last_seen'] = now
		if nbytes >= sample_bytes and send_dt > 0 and (nbytes / send_dt) < min_bps:
			was_slow         = c['slow_until'] > now
			c['slow_until']  = now + hours * 3600
			return not was_slow
	return False


def active_clients(max_rows: int = 8) -> list[tuple[str, float | None]]:
	"""Prune idle, non-slow clients and return up to `max_rows` active ones as
	(ip, slow_seconds_remaining_or_None), slow clients first then most-recently-seen."""
	now    = time.time()
	window = config_get('slowClientActiveWindowSec', 60)
	with lock:
		for ip in [ip for ip, c in clients.items()
				   if c['last_seen'] < now - window and c['slow_until'] <= now]:
			del clients[ip]
		rows = [
			(ip, (c['slow_until'] - now) if c['slow_until'] > now else None, c['last_seen'])
			for ip, c in clients.items()
		]
	# slow clients first, then most recently seen
	rows.sort(key=lambda r: (r[1] is None, -r[2]))
	return [(ip, rem) for ip, rem, _ in rows[:max_rows]]
