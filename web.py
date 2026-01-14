from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, timezone
import subprocess
import fcntl
import os

from database import Database


def is_backup_running() -> bool:
    """Check if a backup is currently running by testing the lock file."""
    lock_file = '/tmp/pgbak.lock'
    if not os.path.exists(lock_file):
        return False
    try:
        fp = open(lock_file, 'w')
        fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.lockf(fp, fcntl.LOCK_UN)
        fp.close()
        return False
    except IOError:
        return True

app = FastAPI(title="PgBak Web UI")

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


def relative_time(value: str) -> str:
    """Convert timestamp (YYYYMMDDTHHMMSS) to relative time string."""
    if not value:
        return "-"
    try:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt

        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''} ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = hours // 24
        if days < 30:
            return f"{days} day{'s' if days != 1 else ''} ago"
        months = days // 30
        if months < 12:
            return f"{months} month{'s' if months != 1 else ''} ago"
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"
    except ValueError:
        return value


templates.env.filters["relative_time"] = relative_time


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page with servers grid."""
    db = Database()
    try:
        servers = db.get_all_servers_for_list()
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "servers": servers}
        )
    finally:
        db.close()


@app.get("/add", response_class=HTMLResponse)
async def add_form(request: Request):
    """Show add server form."""
    return templates.TemplateResponse(
        "form.html",
        {"request": request, "server": None, "action": "add"}
    )


@app.post("/add")
async def add_server(
    connection_string: str = Form(...),
    frequency_hrs: int = Form(...),
    B2_KEY_ID: Optional[str] = Form(None),
    B2_APP_KEY: Optional[str] = Form(None),
    B2_BUCKET: Optional[str] = Form(None),
    archive_name: Optional[str] = Form(None),
    archive_password: Optional[str] = Form(None),
    hc_url_start: Optional[str] = Form(None),
    hc_url_success: Optional[str] = Form(None),
    hc_url_fail: Optional[str] = Form(None)
):
    """Add new server."""
    db = Database()
    try:
        db.add_server(
            connection_string=connection_string,
            frequency_hrs=frequency_hrs,
            B2_KEY_ID=B2_KEY_ID if B2_KEY_ID else None,
            B2_APP_KEY=B2_APP_KEY if B2_APP_KEY else None,
            B2_BUCKET=B2_BUCKET if B2_BUCKET else None,
            archive_name=archive_name if archive_name else None,
            archive_password=archive_password if archive_password else None,
            hc_url_start=hc_url_start if hc_url_start else None,
            hc_url_success=hc_url_success if hc_url_success else None,
            hc_url_fail=hc_url_fail if hc_url_fail else None
        )
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.get("/edit/{server_id}", response_class=HTMLResponse)
async def edit_form(request: Request, server_id: int):
    """Show edit server form."""
    db = Database()
    try:
        server = db.get_server_by_id(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        return templates.TemplateResponse(
            "form.html",
            {"request": request, "server": server, "action": "edit"}
        )
    finally:
        db.close()


@app.post("/edit/{server_id}")
async def edit_server(
    server_id: int,
    connection_string: str = Form(...),
    frequency_hrs: int = Form(...),
    B2_KEY_ID: Optional[str] = Form(None),
    B2_APP_KEY: Optional[str] = Form(None),
    B2_BUCKET: Optional[str] = Form(None),
    archive_name: Optional[str] = Form(None),
    archive_password: Optional[str] = Form(None),
    hc_url_start: Optional[str] = Form(None),
    hc_url_success: Optional[str] = Form(None),
    hc_url_fail: Optional[str] = Form(None)
):
    """Update server."""
    db = Database()
    try:
        db.update_server(
            server_id=server_id,
            connection_string=connection_string,
            frequency_hrs=frequency_hrs,
            B2_KEY_ID=B2_KEY_ID if B2_KEY_ID else None,
            B2_APP_KEY=B2_APP_KEY if B2_APP_KEY else None,
            B2_BUCKET=B2_BUCKET if B2_BUCKET else None,
            archive_name=archive_name if archive_name else None,
            archive_password=archive_password if archive_password else None,
            hc_url_start=hc_url_start if hc_url_start else None,
            hc_url_success=hc_url_success if hc_url_success else None,
            hc_url_fail=hc_url_fail if hc_url_fail else None
        )
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.post("/delete/{server_id}")
async def delete_server(server_id: int):
    """Delete server."""
    db = Database()
    try:
        db.delete_server(server_id)
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.post("/run/{server_id}")
async def run_backup(server_id: int):
    """Run backup for a specific server."""
    if is_backup_running():
        return JSONResponse(
            status_code=409,
            content={"error": "A backup is already running"}
        )

    db = Database()
    try:
        server = db.get_server_by_id(server_id)
        if not server:
            return JSONResponse(
                status_code=404,
                content={"error": "Server not found"}
            )
    finally:
        db.close()

    subprocess.Popen(
        ["pipenv", "run", "python", "main.py", "run", "--force", "--server", str(server_id)],
        cwd="/app",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return JSONResponse(content={"success": True, "message": "Backup started"})


@app.get("/logs/{server_id}", response_class=HTMLResponse)
async def view_logs(request: Request, server_id: int):
    """View backup logs for a server."""
    db = Database()
    try:
        server = db.get_server_by_id(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        logs = db.get_backup_logs(server_id)
        return templates.TemplateResponse(
            "logs.html",
            {"request": request, "server": server, "logs": logs}
        )
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
