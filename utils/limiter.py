from slowapi import Limiter
from slowapi.util import get_remote_address

# Standard limiter using the remote IP address
limiter = Limiter(key_func=get_remote_address)