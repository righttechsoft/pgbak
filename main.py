import logging
import os
import sqlite3
import subprocess
import sys
import traceback
from datetime import datetime
from tempfile import TemporaryDirectory

import b2sdk.v2 as b2
import requests
from logdna import LogDNAHandler

from single_instance_helper import SingleInstance

logger = logging.getLogger()
logger.setLevel(logging.INFO)

options = {
    'app': 'pgbak',
    'hostname': os.getenv('LOG_HOSTNAME')
}

MEZMO_INGESTION_KEY = os.environ['MEZMO_INGESTION_KEY']
log_handler = LogDNAHandler(MEZMO_INGESTION_KEY, options)
logger.addHandler(log_handler)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[pgbak] %(levelname)s: %(message)s"))
logger.addHandler(handler)

me = SingleInstance('pgbak')


def upload_to_b2(b2_key_id: str, b2_app_key: str, b2_bucket: str, backup_filename: str):
    info = b2.InMemoryAccountInfo()
    b2_api = b2.B2Api(info)
    b2_api.authorize_account("production", b2_key_id, b2_app_key)
    bucket = b2_api.get_bucket_by_name(b2_bucket)
    uploaded_file = bucket.upload_local_file(
        local_file=backup_filename,
        file_name=backup_filename
    )
    return uploaded_file


def create_backup(pg_conn_string: str, backup_filename: str, archive_password):
    cmd = f'/usr/bin/pg_dump -d {pg_conn_string} | 7z a -si -p"{archive_password}" -mhe=on -mx=9 "{backup_filename}"'
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True, shell=True)
    popen.wait()


with TemporaryDirectory() as temp_dir:
    os.chdir(temp_dir)
    logger.debug(f'Created tmp dir {temp_dir}')
    conn = sqlite3.connect('/usr/local/etc/pgback/backup.sqlite', isolation_level=None)
    c = conn.execute('SELECT * FROM servers')
    rows = c.fetchall()
    c.close()

    for row in rows:
        last_bak = datetime.strptime(row['last_backup'], '%Y%m%dT%H%M%S')
        time_diff = datetime.utcnow() - last_bak
        hours_diff = time_diff.total_seconds() / 3600
        if hours_diff < row['frequency_hrs']:
            continue
        try:
            connection_string = f'postgres://{row["user"]}:{row["password"]}@{row["host"]}:{row["port"]}/{row["database"]}'
            backup_filename = f'{row["archive_name"]}_{datetime.utcnow().strftime("%Y%m%dT%H%M%S")}.7z'

            logger.debug(f'Create backup {row["host"]} / {row["database"]} to {backup_filename}')
            archive_password = row['archive_password'] if row['archive_password'] else os.environ.get('ARCHIVE_PASSWORD')
            create_backup(connection_string, backup_filename, archive_password)
            filesize = os.path.getsize(backup_filename)
            logger.debug(f'Upload {backup_filename} to B2')
            b2_key_id = row['B2_KEY_ID'] if row['B2_KEY_ID'] else os.environ.get('B2_KEY_ID')
            b2_app_key = row['B2_APP_KEY'] if row['B2_APP_KEY'] else os.environ.get('B2_APP_KEY')
            b2_bucket = row['B2_BUCKET'] if row['B2_BUCKET'] else os.environ.get('B2_BUCKET')
            uploaded_file = upload_to_b2(b2_key_id, b2_app_key, b2_bucket, backup_filename)
            logger.info('Success')

            conn.execute("""
            INSERT INTO backup_log (server_id, ts, "result", file_size) VALUES(?, ?, 'Success', ?)
            """, (row['id'], datetime.utcnow().strftime("%Y%m%dT%H%M%S"), filesize))
            conn.execute("UPDATE servers SET last_backup=?, last_backup_result='Success' WHERE id=?", (datetime.utcnow().strftime("%Y%m%dT%H%M%S"), row['id']))
            if row['dms_id']:
                requests.post(f"https://nosnch.in/{row['dms_id']}", data={"m": uploaded_file})
        except:
            exc = traceback.format_exc()
            conn.execute("""
            INSERT INTO backup_log (server_id, ts, "result", success) VALUES(?, ?, ?, '0')
            """, (row['id'], datetime.utcnow().strftime("%Y%m%dT%H%M%S"), exc))
            logger.error(f'Failed to backup {row["host"]} / {row["database"]}:\n{exc}')
