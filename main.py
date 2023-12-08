import logging
import traceback
import subprocess
import os

from tempfile import TemporaryDirectory

from base import BaseScript
from asyncpg import Connection


class OrdersFromBc(BaseScript):
    def __init__(self, name: str):
        super().__init__(name)

    async def work(self):
        with TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            connection_string_rows = await self.get_db_connection_strings()
            for cs_row in connection_string_rows:
                connection_string = f'postgres://{cs_row["user"]}:{cs_row["password"]}@{cs_row["host"]}:{cs_row["port"]}/{cs_row["database"]}'
                backup_filename = f'{cs_row["database"]}.7z'
                self.create_backup(connection_string, backup_filename)
                self.upload_to_b2(os.environ.get('B2_KEY_ID'), os.environ.get('B2_APP_KEY'),
                                  os.environ.get('B2_BUCKET'), backup_filename)


    def create_backup(self, pg_conn_string: str, backup_filename: str):
        ARCHIVE_PASSWORD = os.environ.get('ARCHIVE_PASSWORD')
        cmd = f'/usr/bin/pg_dump -d {pg_conn_string} | 7z a -si -p"{ARCHIVE_PASSWORD}" -mhe=on -mx=9 "{backup_filename}"'
        popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True, shell=True)
        popen.wait()

    def upload_to_b2(self, b2_key_id: str, b2_app_key: str, b2_bucket: str, backup_filename: str):
        cmd = f'b2 authorize-account "{b2_key_id}" "{b2_app_key}" && b2 upload-file --noProgress "{b2_bucket}" "{backup_filename}" "{backup_filename}"'
        popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True, shell=True)
        popen.wait()

    async def get_db_connection_strings(self):
        rows = list()
        await self.db.connect()
        try:
            async with self.db.get_pool().acquire() as context:
                context: Connection = context
                rows = await context.fetch('SELECT * FROM servers')
        except Exception:
            logging.error(traceback.format_exc())
        finally:
            await self.db.disconnect()

        return rows


if __name__ == '__main__':
    script = OrdersFromBc('orders')
    script.run()


