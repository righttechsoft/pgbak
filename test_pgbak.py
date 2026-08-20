"""Self-check for the backup guards. Run: pipenv run python test_pgbak.py"""
import os
import shutil
import tempfile

import main

# --- size guard: a shrinking archive is a failed dump, a growing one is fine ---
assert main.size_dropped(1000, 899) is True
assert main.size_dropped(1000, 900) is False   # exactly -10% is still allowed
assert main.size_dropped(1000, 5000) is False
assert main.size_dropped(None, 1) is False     # first ever backup has no baseline
assert main.size_dropped(0, 1) is False

# --- connection string parsing ---
c = main.parse_postgres_connection_string('postgresql://user:pass@db.example.com:5433/mydb')
assert c['host'] == 'db.example.com' and c['port'] == 5433 and c['database'] == 'mydb', c
c = main.parse_postgres_connection_string('')
assert c['host'] is None and c['database'] == '', c

# --- a dump that cannot run must raise, not produce a tiny "successful" archive ---
if shutil.which('pg_dump') and shutil.which('7z'):
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            main.create_backup('postgresql://nobody@127.0.0.1:1/nodb', 'x.sql.7z', None)
            raise AssertionError('create_backup reported success for an unreachable database')
        except AssertionError:
            raise
        except Exception as e:
            assert 'pg_dump exited with' in str(e), e
        finally:
            os.chdir(cwd)
else:
    print('skipped create_backup check (pg_dump/7z not installed)')

print('ok')
