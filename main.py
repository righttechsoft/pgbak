import argparse
import logging
import math
import os
import sqlite3
import subprocess
import sys
import traceback
import datetime
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import b2sdk.v2 as b2
import requests
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.validation import Validator, ValidationError
from tabulate import tabulate
from single_instance_helper import SingleInstance

me = SingleInstance('pgbak')

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MEZMO_INGESTION_KEY = os.environ['MEZMO_INGESTION_KEY']
if MEZMO_INGESTION_KEY:
    from logdna import LogDNAHandler

    hostname = os.getenv('LOG_HOSTNAME')
    if not hostname:
        import socket

        hostname = socket.gethostname()

    options = {
        'app': 'pgbak',
        'hostname': hostname
    }

    log_handler = LogDNAHandler(MEZMO_INGESTION_KEY, options)
    logger.addHandler(log_handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[pgbak] %(levelname)s: %(message)s"))
    logger.addHandler(handler)

    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.ERROR)


def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

def handle_error(func):
    def __inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            handle_exception(exc_type, exc_value, exc_tb)

    return __inner

sys.excepthook = handle_exception

def parse_postgres_connection_string(connection_string):
    result = {}
    parsed = urlparse(connection_string)

    result['scheme'] = parsed.scheme
    result['username'] = parsed.username
    result['password'] = parsed.password
    result['host'] = parsed.hostname
    result['port'] = parsed.port
    result['database'] = parsed.path[1:]

    return result


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


from typing import Optional, List
import subprocess
import logging

logger = logging.getLogger(__name__)


def create_backup(
        pg_conn_string: str,
        backup_filename: str,
        archive_password: str,
        exclude_tables: Optional[List[str]] = None
):
    pg_dump_command = f'pg_dump -d {pg_conn_string} -F c -b -v'

    if exclude_tables:
        cleaned_tables = [table.strip() for table in exclude_tables if table.strip()]
        if cleaned_tables:
            exclusion_params = ' '.join(f'--exclude-table="{table}"' for table in cleaned_tables)
            pg_dump_command = f'{pg_dump_command} {exclusion_params}'
            logger.info(f'Excluding tables from backup: {", ".join(cleaned_tables)}')

    seven_zip_command = (
        f'7z a -si -p"{archive_password}" -mhe=on -md=1m -ms=off '
        f'-mx=1 -mm=LZMA2 -mmt=1 {backup_filename}'
    )

    pg_dump_process = subprocess.Popen(
        pg_dump_command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    seven_zip_process = subprocess.Popen(
        seven_zip_command,
        shell=True,
        stdin=pg_dump_process.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    pg_dump_process.stdout.close()

    pg_dump_stderr = pg_dump_process.stderr.read()
    _, seven_zip_stderr = seven_zip_process.communicate()

    if pg_dump_process.returncode != 0:
        raise Exception(f'Error occurred during database dump:\n{pg_dump_stderr.decode("utf-8")}')

    if seven_zip_process.returncode == 0:
        logger.info(f'Database backup created and compressed successfully: {backup_filename}')
    else:
        raise Exception(f'Error occurred during backup compression:\n{seven_zip_stderr.decode("utf-8")}')

def run_backup(conn, force=False, server_id=None):
    with TemporaryDirectory() as temp_dir:
        os.chdir(temp_dir)
        logger.debug(f'Created tmp dir {temp_dir}')
        sql = 'SELECT * FROM servers'
        if server_id:
            sql += f' WHERE id = {server_id}'
        c = conn.execute(sql)
        rows = c.fetchall()
        c.close()

        for row in rows:
            if row['last_backup'] and not force:
                last_bak = datetime.datetime.strptime(row['last_backup'], '%Y%m%dT%H%M%S')
                last_bak_utc = last_bak.replace(tzinfo=datetime.UTC)
                now_utc = datetime.datetime.now(datetime.UTC)
                time_diff = now_utc - last_bak_utc
                hours_diff = time_diff.total_seconds() / 3600
                if hours_diff < row['frequency_hrs']:
                    continue
            try:
                connection_string = row['connection_string']
                # backup_filename = f'{row["archive_name"]}_{datetime.utcnow().strftime("%Y%m%dT%H%M%S")}.7z'
                backup_filename = f'{row["archive_name"]}.7z'
                conn_details = parse_postgres_connection_string(connection_string)

                logger.info(f'Creating backup {conn_details["host"]}/{conn_details["database"]} to {backup_filename}')
                archive_password = row['archive_password'] if row['archive_password'] else os.environ.get('ARCHIVE_PASSWORD')
                create_backup(connection_string, backup_filename, archive_password)
                filesize = os.path.getsize(backup_filename)

                logger.info(f'Uploading {backup_filename} to B2')
                b2_key_id = row['B2_KEY_ID'] if row['B2_KEY_ID'] else os.environ.get('B2_KEY_ID')
                b2_app_key = row['B2_APP_KEY'] if row['B2_APP_KEY'] else os.environ.get('B2_APP_KEY')
                b2_bucket = row['B2_BUCKET'] if row['B2_BUCKET'] else os.environ.get('B2_BUCKET')
                uploaded_file = upload_to_b2(b2_key_id, b2_app_key, b2_bucket, backup_filename)
                logger.info(f'Success {uploaded_file=}')

                conn.execute("""
                INSERT INTO backup_log (server_id, ts, "result", file_size) VALUES(?, ?, 'Success', ?)
                """, (row['id'], datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S"), filesize))
                conn.execute("UPDATE servers SET last_backup=?, last_backup_result='Success' WHERE id=?", (datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S"), row['id']))
                if row['dms_id']:
                    requests.post(f"https://nosnch.in/{row['dms_id']}", data={"m": uploaded_file})

                c = conn.execute('SELECT file_size FROM backup_log bl WHERE server_id=? ORDER BY ts DESC LIMIT 1', (row['id'],))
                prev = c.fetchone()
                c.close()
                diff = abs(prev['file_size'] - filesize) / ((prev['file_size'] + filesize) / 2) * 100
                if diff > 10:
                    logger.error(f'The file size of {conn_details["host"]}/{conn_details["database"]} differs from the previous one by {diff}%! Was: {prev["file_size"]}, now: {filesize}')
            except:
                exc = traceback.format_exc()
                conn.execute("""
                INSERT INTO backup_log (server_id, ts, "result", success) VALUES(?, ?, ?, '0')
                """, (row['id'], datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S"), exc))
                logger.error(f'Failed to backup {conn_details["host"]} / {conn_details["database"]}:\n{exc}')


class NumberValidator(Validator):
    def validate(self, document):
        text = document.text
        if text and not text.isdigit():
            i = 0
            for i, c in enumerate(text):
                if not c.isdigit():
                    break

            raise ValidationError(message='This input contains non-numeric characters',
                                  cursor_position=i)


class NotEmptyValidator(Validator):
    def validate(self, document):
        if document.text == '':
            raise ValidationError(message='Enter the value')


def command_add(conn):
    connection_string = prompt('connection_string: ', validator=NotEmptyValidator())
    frequency_hrs = int(prompt('frequency_hrs: ', validator=NumberValidator()))
    dms_id = prompt('dms_id: ')
    dms_id = None if dms_id == '' else dms_id
    B2_KEY_ID = prompt('B2_KEY_ID: ')
    B2_KEY_ID = None if B2_KEY_ID == '' else B2_KEY_ID
    B2_APP_KEY = prompt('B2_APP_KEY: ')
    B2_APP_KEY = None if B2_APP_KEY == '' else B2_APP_KEY
    B2_BUCKET = prompt('B2_BUCKET: ')
    B2_BUCKET = None if B2_BUCKET == '' else B2_BUCKET
    archive_name = prompt('archive_name: ')
    archive_password = prompt('archive_password: ')
    archive_password = None if archive_password == '' else archive_password
    conn.execute("""
    INSERT INTO servers (connection_string, frequency_hrs, dms_id, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password) 
                  VALUES(?, ?, ?, ?, ?, ?, ?, ?)
    """,
                 (connection_string, frequency_hrs, dms_id, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password))


def command_edit(conn):
    result = ask_for_database(conn)
    if not result:
        return
    c = conn.execute('select * from servers where id=?', (result,))
    row = c.fetchone()
    c.close()

    connection_string = prompt('connection_string: ', default=row['connection_string'], validator=NotEmptyValidator())
    frequency_hrs = int(prompt('frequency_hrs: ', default=str(row['frequency_hrs']), validator=NumberValidator()))
    dms_id = prompt('dms_id: ', default=row['dms_id'] if row['dms_id'] else '')
    dms_id = None if dms_id == '' else dms_id
    B2_KEY_ID = prompt('B2_KEY_ID: ', default=row['B2_KEY_ID'] if row['B2_KEY_ID'] else '')
    B2_KEY_ID = None if B2_KEY_ID == '' else B2_KEY_ID
    B2_APP_KEY = prompt('B2_APP_KEY: ', default=row['B2_APP_KEY'] if row['B2_APP_KEY'] else '')
    B2_APP_KEY = None if B2_APP_KEY == '' else B2_APP_KEY
    B2_BUCKET = prompt('B2_BUCKET: ', default=row['B2_BUCKET'] if row['B2_BUCKET'] else '')
    B2_BUCKET = None if B2_BUCKET == '' else B2_BUCKET
    archive_name = prompt('archive_name: ', default=row['archive_name'])
    archive_password = prompt('archive_password: ', default=row['archive_password'] if row['archive_password'] else '')
    archive_password = None if archive_password == '' else archive_password
    conn.execute("""
    UPDATE servers SET connection_string=?, frequency_hrs=?, dms_id=?, B2_KEY_ID=?, B2_APP_KEY=?, B2_BUCKET=?, archive_name=?, archive_password=? 
                  where id = ?
    """, (connection_string, frequency_hrs, dms_id, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password, row['id']))


def ask_for_database(conn):
    c = conn.execute('select id, connection_string from servers')
    rows = c.fetchall()
    c.close()
    values = list()
    for row in rows:
        conn_details = parse_postgres_connection_string(row['connection_string'])
        value = (row['id'], f"{conn_details['host']}/{conn_details['database']}")
        values.append(value)
    result = radiolist_dialog(
        title="Edit",
        text="What database?",
        values=values
    ).run()
    return result


def command_list(conn):
    c = conn.execute('''
            SELECT id,
                   connection_string ,
                   frequency_hrs ,                
                   IFNULL(B2_KEY_ID,'') B2_KEY_ID, 
                   IFNULL(B2_APP_KEY,'') B2_APP_KEY,
                   IFNULL(B2_BUCKET ,'') B2_BUCKET,
                   IFNULL(archive_name ,'') archive_name, 
                   IFNULL(archive_password ,'') archive_password,
                   IFNULL(dms_id ,'') dms_id,
                   IFNULL(last_backup ,'') last_backup,
                   IFNULL(last_backup_result,'') last_backup_result
            FROM servers
    ''')
    rows = c.fetchall()
    c.close()
    if len(rows) == 0:
        print('Nothing here')
        return
    headers = list(rows[0].keys())

    clwdh = math.floor((200 - 3) / (len(headers)))
    maxcolwidths = [3] + [clwdh] * (len(headers))

    table = tabulate(rows, headers, tablefmt="heavy_grid", maxcolwidths=maxcolwidths)
    print(table)


def command_logs(conn):
    result = ask_for_database(conn)
    if not result:
        return
    c = conn.execute("""
    select ts,"result",ifnull(file_size,'') file_size,success from backup_log where server_id=? order by ts desc
    """, (result,))
    rows = c.fetchall()
    c.close()

    if len(rows) == 0:
        print('Nothing here')
        return
    headers = list(rows[0].keys())

    clwdh = math.floor((200) / len(headers))
    maxcolwidths = [clwdh] * (len(headers))

    table = tabulate(rows, headers, tablefmt="heavy_grid", missingval='', maxcolwidths=maxcolwidths)
    print(table)


def create_db_connection() -> sqlite3.Connection:
    if not os.path.isfile('/usr/local/etc/pgback/backup.sqlite'):
        os.makedirs('/usr/local/etc/pgback/', exist_ok=True)
        conn = sqlite3.connect('/usr/local/etc/pgback/backup.sqlite', isolation_level=None)
        create_tables_script = """
            CREATE TABLE servers (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                connection_string TEXT,
                frequency_hrs INTEGER DEFAULT (1) NOT NULL,                
                B2_KEY_ID TEXT, B2_APP_KEY TEXT, B2_BUCKET TEXT,
                archive_name TEXT, archive_password TEXT,
                dms_id TEXT,
                last_backup TEXT,
                last_backup_result TEXT);
            CREATE TABLE backup_log (
                server_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                "result" TEXT NOT NULL,
                file_size NUMERIC, success TEXT(1) DEFAULT (1) NOT NULL,
                CONSTRAINT backup_log_servers_FK FOREIGN KEY (server_id) REFERENCES servers(id)
            );
        """
        conn.executescript(create_tables_script)
    else:
        conn = sqlite3.connect('/usr/local/etc/pgback/backup.sqlite', isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('command', type=str, choices=['add', 'list', 'logs', 'edit', 'run'])
    parser.add_argument('--force', type=bool, nargs='?', default=False, const=True)
    parser.add_argument('--server', type=int, nargs='?', default=False, const=True)

    args = parser.parse_args()

    conn: sqlite3.Connection = create_db_connection()

    match args.command:
        case 'add':
            command_add(conn)
        case 'edit':
            command_edit(conn)
        case 'list':
            command_list(conn)
        case 'logs':
            command_logs(conn)
        case 'run':
            run_backup(conn, args.force, args.server)
