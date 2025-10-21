<h1>pgbak</h1>

<p><code>pgbak</code> is a Python application for creating and managing backups of PostgreSQL databases. It allows you to configure multiple servers, schedule backups, and upload the compressed backup files to Backblaze B2 storage.</p>

<h2>Features</h2>

<ul>
  <li>Configure multiple PostgreSQL servers for backup</li>
  <li>Schedule backups at specified frequencies</li>
  <li>Compress backups using <code>7z</code> with optional encryption</li>
  <li>Upload backup files to Backblaze B2 storage</li>
  <li>Log backup results and file sizes</li>
  <li>Notify via DeadManSnitch when a backup is successfully uploaded</li>
  <li><strong>Web UI</strong> for easy server management (FastAPI-based)</li>
</ul>

<h2>Installation</h2>

<ol>
  <li>Clone the repository:</li>
</ol>

<pre><code>git clone https://github.com/your-username/pgbak.git</code></pre>

<ol start="2">
  <li>Install the required dependencies:</li>
</ol>

<pre><code>pip install -r requirements.txt</code></pre>

<ol start="3">
  <li>Set the necessary environment variables:</li>
  <ul>
    <li><code>MEZMO_INGESTION_KEY</code>: Mezmo ingestion key for logging (optional)</li>
    <li><code>ARCHIVE_PASSWORD</code>: Default password for encrypting backup archives (optional)</li>
    <li><code>B2_KEY_ID</code>: Default Backblaze B2 key ID (optional)</li>
    <li><code>B2_APP_KEY</code>: Default Backblaze B2 application key (optional)</li>
    <li><code>B2_BUCKET</code>: Default Backblaze B2 bucket name (optional)</li>
  </ul>
</ol>

<h2>Usage</h2>

<h3>Web UI (Recommended)</h3>

<pre><code># Start the web interface
./start_web.sh

# Or manually
python web.py</code></pre>

<p>Open your browser at <code>http://localhost:8000</code> to manage servers through the web interface.</p>

<h3>Command Line Interface</h3>

<pre><code>python main.py [command] [--force]</code></pre>

<p>Available commands:</p>
<ul>
  <li><code>add</code>: Add a new server configuration</li>
  <li><code>edit</code>: Edit an existing server configuration</li>
  <li><code>list</code>: List all configured servers</li>
  <li><code>logs</code>: Display backup logs for a selected server</li>
  <li><code>run</code>: Run the backup process for all configured servers</li>
</ul>

<p>The <code>--force</code> option can be used with the <code>run</code> command to force backups even if the configured frequency has not been reached.</p>

<h2>Configuration</h2>

<p><code>pgbak</code> stores server configurations in an SQLite database located at <code>/usr/local/etc/pgback/backup.sqlite</code>. Each server configuration includes the following parameters:</p>

<ul>
  <li><code>connection_string</code>: PostgreSQL connection string for the server</li>
  <li><code>frequency_hrs</code>: Backup frequency in hours</li>
  <li><code>dms_id</code>: DeadManSnitch ID for notifications (optional)</li>
  <li><code>B2_KEY_ID</code>: Backblaze B2 key ID (optional, overrides the default)</li>
  <li><code>B2_APP_KEY</code>: Backblaze B2 application key (optional, overrides the default)</li>
  <li><code>B2_BUCKET</code>: Backblaze B2 bucket name (optional, overrides the default)</li>
  <li><code>archive_name</code>: Name of the backup archive file</li>
  <li><code>archive_password</code>: Password for encrypting the backup archive (optional, overrides the default)</li>
</ul>

<h2>License</h2>

<p>This project is licensed under the <a href="LICENSE">MIT License</a>.</p>