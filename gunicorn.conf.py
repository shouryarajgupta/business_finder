import multiprocessing

# Number of worker processes
workers = multiprocessing.cpu_count() * 2 + 1

# Timeout for worker processes (120 seconds)
timeout = 120

# Maximum number of requests a worker will process before restarting
max_requests = 1000
max_requests_jitter = 50

# Log level
loglevel = 'info'

# Bind to port 10000 (as detected in your logs)
bind = "0.0.0.0:10000"

# Preload application code
preload_app = True

# Graceful timeout
graceful_timeout = 120 