import threading

lock:             threading.Lock = threading.Lock()
thumbnails_served: int            = 0
bytes_served:      int            = 0
processing_time:   float          = 0.0
requests_served:   int            = 0
