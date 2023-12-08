from typing import Optional

import asyncpg
from asyncpg import Pool


class Database:
    def __init__(self, connection_string: str, min_size: Optional[int], max_size: Optional[int]):
        self._pool: Optional[Pool] = None
        self._connection_string = connection_string
        self._min_size = min_size
        self._max_size = max_size

    async def connect(self):
        self._pool = await asyncpg.create_pool(self._connection_string, min_size=self._min_size,
                                               max_size=self._max_size)

    async def disconnect(self):
        await self._pool.close()

    def get_pool(self):
        return self._pool
