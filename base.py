import asyncio
import logging
import os
import sys
import traceback

from filelock import FileLock
from logdna import LogDNAHandler

from database import Database

MEZMO_INGESTION_KEY = os.environ['MEZMO_INGESTION_KEY']

logger = logging.getLogger('logdna')
logger.setLevel(logging.DEBUG)

options = {
    'app': 'pgbak',
    'hostname': 'Easypanel'
}

log_handler = LogDNAHandler(MEZMO_INGESTION_KEY, options)
logger.addHandler(log_handler)

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[pgbak]: %(levelname)s:%(message)s"))
logger.addHandler(handler)


class BaseScript:
    def __init__(self, name: str):
        self.name = name
        self.db = Database(os.getenv('DATABASE_URL'), int(os.getenv('POOL_MIN_SIZE', default=1)),
                           int(os.getenv('POOL_MAX_SIZE', default=1)))

    def _check_lock(self):
        file_path = f"/tmp/pgbak_{self.name}.lock"
        lock = FileLock(file_path, timeout=1)
        try:
            lock.acquire()
        except:
            logger.error("Process is already running, exiting")
            sys.exit("Process is already running")
        return lock

    def run(self):
        logger.debug(f'Run {self.name}')
        lock = self._check_lock()
        try:
            asyncio.run(self.work())
        except:
            logger.error(traceback.format_exc())
        finally:
            lock.release()
