"""本地 HTTP 服务：REST 接口 + 晨报定时任务（未来仪表盘的后端）。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import cards, db, parser, report
from .push import send_text

app = FastAPI(title="lifehub", version="0.4.0")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


class QuickIn(BaseModel):
    text: str


@app.get("/api/health")
def health():
    return {"ok": True, "db": str(db.CFG.hub.db)}


@app.get("/api/todos")
def get_todos():
    return [dict(r) for r in db.list_todos()]


@app.post("/api/todos")
def quick_add(body: QuickIn):
    p = parser.parse(body.text)
    if p.kind == "event":
        eid = db.add_event(p.title, db.fmt_when(p.when), source="api")  # type: ignore[arg-type]
        return {"kind": "event", "id": eid}
    if p.kind == "ledger":
        lid = db.add_ledger(p.amount, p.category, p.note, source="api",
                            kind=p.direction or "expense")  # type: ignore[arg-type]
        return {"kind": "ledger", "id": lid, "direction": p.direction}
    tid = db.add_todo(p.title, p.when.date().isoformat() if p.when else None,
                      p.priority, source="api")
    return {"kind": "todo", "id": tid}


@app.post("/api/todos/{tid}/done")
def todo_done(tid: int):
    if not db.complete_todo(tid):
        raise HTTPException(404, "没有这条打开状态的待办")
    return {"ok": True}


@app.get("/api/board")
def board_card():
    """待办看板卡片（未来仪表盘/手机端复用）。"""
    return cards.build_todos_card()


@app.get("/api/boards/{name}")
def any_board(name: str):
    return cards.build(name)


@app.post("/api/report/send")
def send_now():
    ok, msg = report.send_report()
    return {"ok": ok, "detail": msg, "preview": report.build_report()}


@app.post("/api/push")
def push_text(body: QuickIn):
    ok, msg = send_text(body.text)
    return {"ok": ok, "detail": msg}
