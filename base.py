import asyncio
import logging
import os
import sys
import traceback

from logging import handlers

from filelock import FileLock

from database import Database

logging.basicConfig(level=logging.NOTSET)
sptimber_logger = logging.getLogger('pgbak')
sptimber_logger.setLevel(logging.NOTSET)
sptimber_logger.propagate = False
handler = handlers.SysLogHandler(address='/dev/log')
handler.setFormatter(logging.Formatter("[pgbak]: %(levelname)s:%(message)s"))
sptimber_logger.addHandler(handler)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[pgbak]: %(levelname)s:%(message)s"))
sptimber_logger.addHandler(handler)


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
            sptimber_logger.error("Process is already running, exiting")
            sys.exit("Process is already running")
        return lock

    def run(self):
        sptimber_logger.debug(f'Run {self.name}')
        lock = self._check_lock()
        try:
            asyncio.run(self.work())
        except:
            sptimber_logger.error(traceback.format_exc())
        finally:
            lock.release()
