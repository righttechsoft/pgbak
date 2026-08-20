import argparse
import logging
import math
import os
import time
import sys
import traceback
import datetime
from tempfile import TemporaryDirectory, TemporaryFile
from urllib.parse import urlparse

import b2sdk.v2 as b2
import requests
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.validation import Validator, ValidationError
from tabulate import tabulate
from single_instance_helper import SingleInstance

from database import Database

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# hard kill for a dump that hangs on a dead connection - it would hold the single-instance
# lock forever and silently starve every later cron run
BACKUP_TIMEOUT_SEC = int(os.environ.get('BACKUP_TIMEOUT_SEC', 4 * 60 * 60))

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[pgbak] %(levelname)s: %(message)s"))
logger.addHandler(handler)

logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

MEZMO_INGESTION_KEY = os.environ.get('MEZMO_INGESTION_KEY')
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


def call_hc(url: str, data: str = None):
    """Call a healthcheck URL with retries."""
    attempt = 1
    while attempt <= 3:
        try:
            logging.info(f'Calling {url}')
            res = requests.post(url, data=data, timeout=60)
            logging.info(f'Result: {res.status_code}')
            res.raise_for_status()
            return
        except:
            logging.info(f'Waiting for {attempt * 10}')
            time.sleep(attempt * 10)
            attempt += 1

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


def pg_dump_error_summary(stderr: str, limit: int = 2000) -> str:
    """Keep the lines that say what went wrong.

    On a failed query pg_dump prints the reason and then the whole failing statement -
    a LOCK TABLE over a few dozen tables is thousands of characters, so a plain tail of
    the log shows only that statement and hides the reason above it.
    """
    errors = [line[:500] for line in stderr.splitlines() if 'error:' in line.lower()]
    return '\n'.join(errors)[-limit:] if errors else stderr[-limit:]


def size_dropped(prev_file_size, filesize, tolerance=0.1) -> bool:
    """True if the new archive is more than `tolerance` smaller than the last good one."""
    return bool(prev_file_size) and filesize < prev_file_size * (1 - tolerance)


def create_backup(
        pg_conn_string: str,
        backup_filename: str,
        archive_password: str,
        exclude_tables: Optional[List[str]] = None,
        format: str = 'sql'  # 'sql' for SQL format, 'binary' for binary format
):
    # argument lists, not shell=True: a password containing $ ` ; & or a space would
    # otherwise be mangled by the shell (or executed by it)
    pg_dump_command = ['pg_dump', '-d', pg_conn_string, '-v']
    pg_dump_command += ['-F', 'p'] if format == 'sql' else ['-F', 'c', '-b']

    if exclude_tables:
        cleaned_tables = [table.strip() for table in exclude_tables if table.strip()]
        if cleaned_tables:
            pg_dump_command += [f'--exclude-table={table}' for table in cleaned_tables]
            logger.info(f'Excluding tables from backup: {", ".join(cleaned_tables)}')

    seven_zip_command = ['7z', 'a', '-si']
    if archive_password:
        seven_zip_command += [f'-p{archive_password}', '-mhe=on']
    seven_zip_command += ['-md=1m', '-ms=off', '-mx=1', '-mm=LZMA2', '-mmt=1', backup_filename]

    # pg_dump -v can emit more than a 64K pipe buffer holds; a file cannot fill up, so the
    # pipeline cannot deadlock while we are blocked waiting on 7z
    with TemporaryFile() as pg_dump_stderr_file:
        pg_dump_process = subprocess.Popen(
            pg_dump_command,
            stdout=subprocess.PIPE,
            stderr=pg_dump_stderr_file
        )

        seven_zip_process = subprocess.Popen(
            seven_zip_command,
            stdin=pg_dump_process.stdout,
            stdout=subprocess.DEVNULL,  # progress chatter would fill the pipe and stall the dump
            stderr=subprocess.PIPE
        )

        pg_dump_process.stdout.close()  # 7z owns the read end now, so pg_dump gets EPIPE if 7z dies

        started = time.monotonic()
        try:
            # the dump itself lives here - it may legitimately run for hours
            _, seven_zip_stderr = seven_zip_process.communicate(timeout=BACKUP_TIMEOUT_SEC)
            # 7z can only have exited once pg_dump closed its stdout, so this just reaps it and
            # sets returncode (reading .stderr never does) - but still bound it by what is left
            pg_dump_process.wait(timeout=max(60, BACKUP_TIMEOUT_SEC - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            seven_zip_process.kill()
            pg_dump_process.kill()
            raise Exception(f'Backup timed out after {BACKUP_TIMEOUT_SEC}s, processes killed')

        pg_dump_stderr_file.seek(0)
        pg_dump_stderr = pg_dump_stderr_file.read().decode('utf-8', 'replace')

    seven_zip_stderr = seven_zip_stderr.decode('utf-8', 'replace')
    logger.info(pg_dump_stderr)
    logger.info(seven_zip_stderr)

    if seven_zip_process.returncode != 0:
        raise Exception(f'Error occurred during backup compression:\n{seven_zip_stderr}')

    # a dump that died halfway still compresses fine - only the exit code says the data is complete
    if pg_dump_process.returncode != 0:
        raise Exception(f'pg_dump exited with {pg_dump_process.returncode}, '
                        f'backup is incomplete:\n{pg_dump_error_summary(pg_dump_stderr)}')

    logger.info(f'Database backup created and compressed successfully: {backup_filename}')


def run_backup(db: Database, force=False, server_id=None, format='sql'):
    with TemporaryDirectory() as temp_dir:
        os.chdir(temp_dir)
        logger.debug(f'Created tmp dir {temp_dir}')
        rows = db.get_servers(server_id)
        if server_id is not None and not rows:
            logger.error(f'No server with id {server_id}')
            return

        used_filenames = set()
        for row in rows:
            conn_details = parse_postgres_connection_string(row['connection_string'] or '')
            label = f'{conn_details["host"]}/{conn_details["database"]}'

            if row['last_backup'] and not force:
                last_bak = datetime.datetime.strptime(row['last_backup'], '%Y%m%dT%H%M%S')
                last_bak_utc = last_bak.replace(tzinfo=datetime.UTC)
                now_utc = datetime.datetime.now(datetime.UTC)
                time_diff = now_utc - last_bak_utc
                hours_diff = time_diff.total_seconds() / 3600
                if hours_diff < row['frequency_hrs']:
                    continue

            backup_filename = None
            try:
                # validate before pinging hc_url_start, otherwise a misconfigured server
                # reports "started" and then never reports anything else
                archive_name = (row['archive_name'] or '').strip()
                if not archive_name:
                    raise Exception(f'Server {row["id"]} ({label}) has no archive_name set')

                extension = '.sql.7z' if format == 'sql' else '.bin.7z'
                backup_filename = f'{archive_name}{extension}'
                # same name twice in one run: 7z would append the second dump into the first
                # archive, and B2 would end up holding only one of the two databases
                if backup_filename in used_filenames:
                    raise Exception(f'archive_name "{archive_name}" is already used by another server')
                used_filenames.add(backup_filename)

                if row['hc_url_start']:
                    call_hc(row['hc_url_start'])

                logger.info(f'Creating {format} backup {label} to {backup_filename}')
                archive_password = row['archive_password'] if row['archive_password'] else os.environ.get('ARCHIVE_PASSWORD')
                create_backup(row['connection_string'], backup_filename, archive_password, format=format)
                filesize = os.path.getsize(backup_filename)

                prev_file_size = db.get_previous_backup_size(row['id'])
                # a shrinking dump means truncated/partial data - fail before it reaches B2
                if size_dropped(prev_file_size, filesize):
                    raise Exception(f'Archive shrank by more than 10%: was {prev_file_size}, now {filesize} bytes')

                logger.info(f'Uploading {backup_filename} to B2')
                b2_key_id = row['B2_KEY_ID'] if row['B2_KEY_ID'] else os.environ.get('B2_KEY_ID')
                b2_app_key = row['B2_APP_KEY'] if row['B2_APP_KEY'] else os.environ.get('B2_APP_KEY')
                b2_bucket = row['B2_BUCKET'] if row['B2_BUCKET'] else os.environ.get('B2_BUCKET')
                uploaded_file = upload_to_b2(b2_key_id, b2_app_key, b2_bucket, backup_filename)
                logger.info(f'Success {uploaded_file=}')

                db.log_backup_success(row['id'], filesize)

                if prev_file_size and filesize > prev_file_size * 1.1:
                    growth = (filesize - prev_file_size) / prev_file_size * 100
                    logger.warning(f'The file size of {label} grew by {growth:.1f}% since the previous backup! Was: {prev_file_size}, now: {filesize}')

                if row['hc_url_success']:
                    call_hc(row['hc_url_success'])

            except Exception:
                exc = traceback.format_exc()
                db.log_backup_failure(row['id'], exc)
                logger.error(f'Failed to backup {label}:\n{exc}')
                if row['hc_url_fail']:
                    call_hc(row['hc_url_fail'], data=str(exc))
            finally:
                # do not keep every server archive around until the whole run ends - /tmp is
                # often a tmpfs, and that is RAM
                if backup_filename and os.path.exists(backup_filename):
                    os.remove(backup_filename)


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


def command_add(db: Database):
    connection_string = prompt('connection_string: ', validator=NotEmptyValidator())
    frequency_hrs = int(prompt('frequency_hrs: ', validator=NumberValidator()))
    B2_KEY_ID = prompt('B2_KEY_ID: ')
    B2_KEY_ID = None if B2_KEY_ID == '' else B2_KEY_ID
    B2_APP_KEY = prompt('B2_APP_KEY: ')
    B2_APP_KEY = None if B2_APP_KEY == '' else B2_APP_KEY
    B2_BUCKET = prompt('B2_BUCKET: ')
    B2_BUCKET = None if B2_BUCKET == '' else B2_BUCKET
    archive_name = prompt('archive_name: ')
    archive_password = prompt('archive_password: ')
    archive_password = None if archive_password == '' else archive_password
    hc_url_start = prompt('hc_url_start: ')
    hc_url_start = None if hc_url_start == '' else hc_url_start
    hc_url_success = prompt('hc_url_success: ')
    hc_url_success = None if hc_url_success == '' else hc_url_success
    hc_url_fail = prompt('hc_url_fail: ')
    hc_url_fail = None if hc_url_fail == '' else hc_url_fail
    db.add_server(connection_string, frequency_hrs, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password, hc_url_start, hc_url_success, hc_url_fail)


def command_edit(db: Database):
    result = ask_for_database(db)
    if not result:
        return
    row = db.get_server_by_id(result)

    connection_string = prompt('connection_string: ', default=row['connection_string'], validator=NotEmptyValidator())
    frequency_hrs = int(prompt('frequency_hrs: ', default=str(row['frequency_hrs']), validator=NumberValidator()))
    B2_KEY_ID = prompt('B2_KEY_ID: ', default=row['B2_KEY_ID'] if row['B2_KEY_ID'] else '')
    B2_KEY_ID = None if B2_KEY_ID == '' else B2_KEY_ID
    B2_APP_KEY = prompt('B2_APP_KEY: ', default=row['B2_APP_KEY'] if row['B2_APP_KEY'] else '')
    B2_APP_KEY = None if B2_APP_KEY == '' else B2_APP_KEY
    B2_BUCKET = prompt('B2_BUCKET: ', default=row['B2_BUCKET'] if row['B2_BUCKET'] else '')
    B2_BUCKET = None if B2_BUCKET == '' else B2_BUCKET
    archive_name = prompt('archive_name: ', default=row['archive_name'])
    archive_password = prompt('archive_password: ', default=row['archive_password'] if row['archive_password'] else '')
    archive_password = None if archive_password == '' else archive_password
    hc_url_start = prompt('hc_url_start: ', default=row['hc_url_start'] if row['hc_url_start'] else '')
    hc_url_start = None if hc_url_start == '' else hc_url_start
    hc_url_success = prompt('hc_url_success: ', default=row['hc_url_success'] if row['hc_url_success'] else '')
    hc_url_success = None if hc_url_success == '' else hc_url_success
    hc_url_fail = prompt('hc_url_fail: ', default=row['hc_url_fail'] if row['hc_url_fail'] else '')
    hc_url_fail = None if hc_url_fail == '' else hc_url_fail
    db.update_server(row['id'], connection_string, frequency_hrs, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password, hc_url_start, hc_url_success, hc_url_fail)

def command_del(db: Database):
    result = ask_for_database(db)
    if not result:
        return
    db.delete_server(result)

def ask_for_database(db: Database):
    rows = db.get_servers()
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


def command_list(db: Database):
    rows = db.get_all_servers_for_list()
    if len(rows) == 0:
        print('Nothing here')
        return
    headers = list(rows[0].keys())

    clwdh = math.floor((200 - 3) / (len(headers)))
    maxcolwidths = [3] + [clwdh] * (len(headers))

    table = tabulate(rows, headers, tablefmt="heavy_grid", maxcolwidths=maxcolwidths)
    print(table)


def command_logs(db: Database):
    result = ask_for_database(db)
    if not result:
        return
    rows = db.get_backup_logs(result)

    if len(rows) == 0:
        print('Nothing here')
        return
    headers = list(rows[0].keys())

    clwdh = math.floor((200) / len(headers))
    maxcolwidths = [clwdh] * (len(headers))

    table = tabulate(rows, headers, tablefmt="heavy_grid", missingval='', maxcolwidths=maxcolwidths)
    print(table)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('command', type=str, choices=['add', 'del', 'list', 'logs', 'edit', 'run'])
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--server', type=int, default=None)
    parser.add_argument('--format', type=str, choices=['sql', 'binary'], default='sql', 
                       help='Backup format: sql (plain SQL) or binary (PostgreSQL custom format)')

    args = parser.parse_args()

    db = Database()

    match args.command:
        case 'add':
            command_add(db)
        case 'del':
            command_del(db)
        case 'edit':
            command_edit(db)
        case 'list':
            command_list(db)
        case 'logs':
            command_logs(db)
        case 'run':
            # only 'run' needs the lock; editing the config while a backup runs is harmless
            me = SingleInstance('pgbak')
            run_backup(db, args.force, args.server, args.format)
