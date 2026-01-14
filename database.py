import sqlite3
import os
import datetime
from typing import Optional, List, Dict, Any

class Database:
    def __init__(self):
        """
        Initialize Database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = os.getenv('DB_PATH', 'backup.sqlite') #'/usr/local/etc/pgback/backup.sqlite'
        self.conn = None
        self._initialize()
    
    def _initialize(self):
        """Initialize database connection and create tables if needed."""
        if not os.path.isfile(self.db_path):
            if os.path.dirname(self.db_path):
                os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self.conn = sqlite3.connect(self.db_path, isolation_level=None)
            self._create_tables()
        else:
            self.conn = sqlite3.connect(self.db_path, isolation_level=None)

        self.conn.row_factory = sqlite3.Row
        self._migrate_schema()
    
    def _create_tables(self):
        """Create database tables."""
        create_tables_script = """
            CREATE TABLE servers (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                connection_string TEXT,
                frequency_hrs INTEGER DEFAULT (1) NOT NULL,                
                B2_KEY_ID TEXT, B2_APP_KEY TEXT, B2_BUCKET TEXT,
                archive_name TEXT, archive_password TEXT,
                hc_url_start TEXT,
                hc_url_success TEXT,
                hc_url_fail TEXT,
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
        self.conn.executescript(create_tables_script)

    def _migrate_schema(self):
        """Migrate database schema to current version."""
        cursor = self.conn.execute("PRAGMA table_info(servers)")
        columns = {row[1] for row in cursor.fetchall()}
        cursor.close()

        # Remove obsolete columns
        obsolete_columns = ['port', 'database', 'user', 'password', 'keep_last_files']
        for col in obsolete_columns:
            if col in columns:
                self.conn.execute(f'ALTER TABLE servers DROP COLUMN "{col}"')

        # Migrate dms_id to hc_url_success and add new healthcheck columns
        if 'dms_id' in columns:
            self.conn.execute('ALTER TABLE servers RENAME COLUMN dms_id TO hc_url_success')
        if 'hc_url_start' not in columns:
            self.conn.execute('ALTER TABLE servers ADD COLUMN hc_url_start TEXT')
        if 'hc_url_fail' not in columns:
            self.conn.execute('ALTER TABLE servers ADD COLUMN hc_url_fail TEXT')

    def get_servers(self, server_id: Optional[int] = None) -> List[sqlite3.Row]:
        """
        Get servers from database.
        
        Args:
            server_id: Optional server ID to filter by
            
        Returns:
            List of server rows
        """
        sql = 'SELECT * FROM servers'
        if server_id:
            sql += f' WHERE id = {server_id}'
        c = self.conn.execute(sql)
        rows = c.fetchall()
        c.close()
        return rows
    
    def get_server_by_id(self, server_id: int) -> Optional[sqlite3.Row]:
        """
        Get a single server by ID.
        
        Args:
            server_id: Server ID
            
        Returns:
            Server row or None
        """
        c = self.conn.execute('SELECT * FROM servers WHERE id=?', (server_id,))
        row = c.fetchone()
        c.close()
        return row
    
    def add_server(self, connection_string: str, frequency_hrs: int,
                   B2_KEY_ID: Optional[str] = None, B2_APP_KEY: Optional[str] = None,
                   B2_BUCKET: Optional[str] = None, archive_name: Optional[str] = None,
                   archive_password: Optional[str] = None, hc_url_start: Optional[str] = None,
                   hc_url_success: Optional[str] = None, hc_url_fail: Optional[str] = None):
        """
        Add a new server to the database.

        Args:
            connection_string: PostgreSQL connection string
            frequency_hrs: Backup frequency in hours
            B2_KEY_ID: Backblaze B2 Key ID (optional)
            B2_APP_KEY: Backblaze B2 App Key (optional)
            B2_BUCKET: Backblaze B2 Bucket name (optional)
            archive_name: Archive file name (optional)
            archive_password: Archive password (optional)
            hc_url_start: Healthcheck URL to call on backup start (optional)
            hc_url_success: Healthcheck URL to call on backup success (optional)
            hc_url_fail: Healthcheck URL to call on backup failure (optional)
        """
        self.conn.execute("""
        INSERT INTO servers (connection_string, frequency_hrs, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password, hc_url_start, hc_url_success, hc_url_fail)
                      VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (connection_string, frequency_hrs, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password, hc_url_start, hc_url_success, hc_url_fail))
    
    def update_server(self, server_id: int, connection_string: str, frequency_hrs: int,
                      B2_KEY_ID: Optional[str] = None, B2_APP_KEY: Optional[str] = None,
                      B2_BUCKET: Optional[str] = None, archive_name: Optional[str] = None,
                      archive_password: Optional[str] = None, hc_url_start: Optional[str] = None,
                      hc_url_success: Optional[str] = None, hc_url_fail: Optional[str] = None):
        """
        Update an existing server.

        Args:
            server_id: Server ID to update
            connection_string: PostgreSQL connection string
            frequency_hrs: Backup frequency in hours
            B2_KEY_ID: Backblaze B2 Key ID (optional)
            B2_APP_KEY: Backblaze B2 App Key (optional)
            B2_BUCKET: Backblaze B2 Bucket name (optional)
            archive_name: Archive file name (optional)
            archive_password: Archive password (optional)
            hc_url_start: Healthcheck URL to call on backup start (optional)
            hc_url_success: Healthcheck URL to call on backup success (optional)
            hc_url_fail: Healthcheck URL to call on backup failure (optional)
        """
        self.conn.execute("""
        UPDATE servers SET connection_string=?, frequency_hrs=?, B2_KEY_ID=?, B2_APP_KEY=?, B2_BUCKET=?, archive_name=?, archive_password=?, hc_url_start=?, hc_url_success=?, hc_url_fail=?
                      WHERE id = ?
        """, (connection_string, frequency_hrs, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, archive_name, archive_password, hc_url_start, hc_url_success, hc_url_fail, server_id))
    
    def delete_server(self, server_id: int):
        """
        Delete a server and its backup logs.
        
        Args:
            server_id: Server ID to delete
        """
        self.conn.execute('DELETE FROM backup_log WHERE server_id=?', (server_id,))
        self.conn.execute('DELETE FROM servers WHERE id=?', (server_id,))
    
    def get_all_servers_for_list(self) -> List[sqlite3.Row]:
        """
        Get all servers with formatted fields for listing.
        
        Returns:
            List of server rows with IFNULL applied
        """
        c = self.conn.execute('''
            SELECT id,
                   connection_string ,
                   frequency_hrs ,                
                   IFNULL(B2_KEY_ID,'') B2_KEY_ID, 
                   IFNULL(B2_APP_KEY,'') B2_APP_KEY,
                   IFNULL(B2_BUCKET ,'') B2_BUCKET,
                   IFNULL(archive_name ,'') archive_name, 
                   IFNULL(archive_password ,'') archive_password,
                   IFNULL(hc_url_start ,'') hc_url_start,
                   IFNULL(hc_url_success ,'') hc_url_success,
                   IFNULL(hc_url_fail ,'') hc_url_fail,
                   IFNULL(last_backup ,'') last_backup,
                   IFNULL(last_backup_result,'') last_backup_result
            FROM servers
        ''')
        rows = c.fetchall()
        c.close()
        return rows
    
    def get_backup_logs(self, server_id: int) -> List[sqlite3.Row]:
        """
        Get backup logs for a specific server.
        
        Args:
            server_id: Server ID
            
        Returns:
            List of backup log rows
        """
        c = self.conn.execute("""
        SELECT ts, "result", IFNULL(file_size,'') file_size, success 
        FROM backup_log 
        WHERE server_id=? 
        ORDER BY ts DESC
        """, (server_id,))
        rows = c.fetchall()
        c.close()
        return rows
    
    def log_backup_success(self, server_id: int, file_size: int):
        """
        Log a successful backup.
        
        Args:
            server_id: Server ID
            file_size: Size of the backup file in bytes
        """
        ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
        self.conn.execute("""
        INSERT INTO backup_log (server_id, ts, "result", file_size) 
        VALUES(?, ?, 'Success', ?)
        """, (server_id, ts, file_size))
        
        self.conn.execute("""
        UPDATE servers 
        SET last_backup=?, last_backup_result='Success' 
        WHERE id=?
        """, (ts, server_id))
    
    def log_backup_failure(self, server_id: int, error_message: str):
        """
        Log a failed backup.

        Args:
            server_id: Server ID
            error_message: Error message/traceback
        """
        ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
        self.conn.execute("""
        INSERT INTO backup_log (server_id, ts, "result", success)
        VALUES(?, ?, ?, '0')
        """, (server_id, ts, error_message))

        self.conn.execute("""
        UPDATE servers
        SET last_backup=?, last_backup_result='Failed'
        WHERE id=?
        """, (ts, server_id))
    
    def get_previous_backup_size(self, server_id: int) -> Optional[int]:
        """
        Get the file size of the previous backup.
        
        Args:
            server_id: Server ID
            
        Returns:
            File size in bytes or None
        """
        c = self.conn.execute("""
        SELECT file_size 
        FROM backup_log 
        WHERE server_id=? 
        ORDER BY ts DESC 
        LIMIT 1
        """, (server_id,))
        prev = c.fetchone()
        c.close()
        return prev['file_size'] if prev else None
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
