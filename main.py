"""
main.py — the DataLens server.

Start it with:   ./run.sh        (from the schema-viz folder)
Then open:       http://localhost:8000

This one server does everything: it serves the web page (the frontend folder)
and answers the page's requests (/upload, /sample, /ask).
"""
import traceback
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analyzer import PlanError, TableError, auto_insights, detect_schema, load_table, run_plan, suggest_questions
from planner import claude_available, make_plan

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"
SAMPLES = ROOT / "sample_data"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(title="DataLens")


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """Show the real reason in the browser instead of a blank 500."""
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Server error ({type(exc).__name__}: {exc}). Send this message to the developer."},
    )

# One dataset in memory at a time. Fine for a demo with a single presenter.
STATE = {"df": None, "schema": None}


class Question(BaseModel):
    question: str


def _open_dataset(filename, raw):
    try:
        df = load_table(filename, raw)
    except TableError as err:
        raise HTTPException(400, str(err))
    schema = detect_schema(df, filename)
    STATE["df"], STATE["schema"] = df, schema
    try:
        insights = auto_insights(df, schema)
    except Exception:
        traceback.print_exc()
        insights = []
    try:
        suggested = suggest_questions(schema)
    except Exception:
        traceback.print_exc()
        suggested = []
    return {"schema": schema, "insights": insights, "suggested_questions": suggested}


@app.get("/health")
def health():
    return {"ok": True, "engine": "claude" if claude_available() else "rules"}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "That file is larger than 10 MB. Please upload a smaller one.")
    return _open_dataset(file.filename or "upload", raw)


@app.get("/samples")
def samples():
    return sorted(p.name for p in SAMPLES.glob("*.csv"))


@app.post("/sample/{name}")
def sample(name: str):
    path = SAMPLES / Path(name).name
    if path.suffix != ".csv" or not path.is_file():
        raise HTTPException(404, "That sample dataset does not exist.")
    return _open_dataset(path.name, path.read_bytes())


@app.post("/ask")
def ask(body: Question):
    if STATE["df"] is None:
        raise HTTPException(400, "Please upload a dataset first.")
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Please type a question.")

    plan, engine, note = make_plan(question, STATE["schema"])
    try:
        result = run_plan(STATE["df"], STATE["schema"], plan)
    except PlanError as err:
        raise HTTPException(422, str(err))
    result["proof"]["engine"] = engine
    if note:
        result["proof"]["note"] = note
    return result


# Keep this last so the routes above win.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
