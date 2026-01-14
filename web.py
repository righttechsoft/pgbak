from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional

from database import Database

app = FastAPI(title="PgBak Web UI")


templates = Jinja2Templates(directory="templates")


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
    dms_id: Optional[str] = Form(None),
    B2_KEY_ID: Optional[str] = Form(None),
    B2_APP_KEY: Optional[str] = Form(None),
    B2_BUCKET: Optional[str] = Form(None),
    archive_name: Optional[str] = Form(None),
    archive_password: Optional[str] = Form(None)
):
    """Add new server."""
    db = Database()
    try:
        db.add_server(
            connection_string=connection_string,
            frequency_hrs=frequency_hrs,
            dms_id=dms_id if dms_id else None,
            B2_KEY_ID=B2_KEY_ID if B2_KEY_ID else None,
            B2_APP_KEY=B2_APP_KEY if B2_APP_KEY else None,
            B2_BUCKET=B2_BUCKET if B2_BUCKET else None,
            archive_name=archive_name if archive_name else None,
            archive_password=archive_password if archive_password else None
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
    dms_id: Optional[str] = Form(None),
    B2_KEY_ID: Optional[str] = Form(None),
    B2_APP_KEY: Optional[str] = Form(None),
    B2_BUCKET: Optional[str] = Form(None),
    archive_name: Optional[str] = Form(None),
    archive_password: Optional[str] = Form(None)
):
    """Update server."""
    db = Database()
    try:
        db.update_server(
            server_id=server_id,
            connection_string=connection_string,
            frequency_hrs=frequency_hrs,
            dms_id=dms_id if dms_id else None,
            B2_KEY_ID=B2_KEY_ID if B2_KEY_ID else None,
            B2_APP_KEY=B2_APP_KEY if B2_APP_KEY else None,
            B2_BUCKET=B2_BUCKET if B2_BUCKET else None,
            archive_name=archive_name if archive_name else None,
            archive_password=archive_password if archive_password else None
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
