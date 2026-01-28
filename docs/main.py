from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="HR Brand BI - ETL API",
    version="1.0.0",
    description="REST API сервиса интеграции данных (ETL).",
)


SOURCES: Dict[str, dict] = {}
PIPELINES: Dict[str, dict] = {}
RUNS: Dict[str, dict] = {}
RUN_LOGS: Dict[str, List[str]] = {}


# Models


SourceType = Literal["review_site", "media", "crm", "contractor"]
SourceStatus = Literal["active", "inactive"]

class SourceCreateRequest(BaseModel):
    source_id: str = Field(..., examples=["dreamjob", "vc_ru", "ancor"])
    type: SourceType
    connection_params: dict = Field(default_factory=dict)
    status: SourceStatus = "active"


class SourceUpdateRequest(BaseModel):
    connection_params: Optional[dict] = None
    status: Optional[SourceStatus] = None


class SourceResponse(BaseModel):
    source_id: str
    type: SourceType
    status: SourceStatus


class PipelineCreateRequest(BaseModel):
    pipeline_id: str = Field(..., examples=["reviews_etl", "content_metrics_etl"])
    sources: List[str] = Field(default_factory=list, examples=[["dreamjob", "otzovik"]])
    target: str = Field(..., examples=["hr_dwh"])
    schedule: Optional[str] = Field(default=None, examples=["0 */6 * * *"])


class PipelineUpdateRequest(BaseModel):
    sources: Optional[List[str]] = None
    target: Optional[str] = None
    schedule: Optional[str] = None


class PipelineResponse(BaseModel):
    pipeline_id: str
    sources: List[str]
    target: str
    schedule: Optional[str]


RunStatus = Literal["queued", "running", "success", "failed"]

class RunCreateRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: str
    pipeline_id: str
    status: RunStatus
    started_at: str
    finished_at: Optional[str] = None


class RunStatusResponse(BaseModel):
    run_id: str
    pipeline_id: str
    status: RunStatus
    started_at: str
    finished_at: Optional[str] = None


class RunLogsResponse(BaseModel):
    run_id: str
    logs: List[str]



# Helpers


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_pipeline_exists(pipeline_id: str) -> dict:
    pipeline = PIPELINES.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
    return pipeline


def ensure_run_exists(run_id: str) -> dict:
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run


# API METHODS
# SOURCES


@app.get("/api/v1/sources", response_model=List[SourceResponse])
def list_sources():
    return [SourceResponse(**v) for v in SOURCES.values()]


@app.post("/api/v1/sources", status_code=201, response_model=SourceResponse)
def create_source(req: SourceCreateRequest):
    if req.source_id in SOURCES:
        raise HTTPException(status_code=409, detail="Source already exists")
    SOURCES[req.source_id] = req.model_dump()
    return SourceResponse(
        source_id=req.source_id,
        type=req.type,
        status=req.status,
    )


@app.put("/api/v1/sources/{source_id}", response_model=SourceResponse)
def update_source(source_id: str, req: SourceUpdateRequest):
    source = SOURCES.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if req.connection_params is not None:
        source["connection_params"] = req.connection_params
    if req.status is not None:
        source["status"] = req.status

    SOURCES[source_id] = source
    return SourceResponse(
        source_id=source_id,
        type=source["type"],
        status=source["status"],
    )


@app.delete("/api/v1/sources/{source_id}", status_code=204)
def delete_source(source_id: str):
    if source_id not in SOURCES:
        raise HTTPException(status_code=404, detail="Source not found")

    for pipeline in PIPELINES.values():
        if source_id in pipeline["sources"]:
            raise HTTPException(
                status_code=400,
                detail="Source is used in pipelines and cannot be deleted",
            )

    del SOURCES[source_id]


# PIPELINES

@app.get("/api/v1/pipelines", response_model=List[PipelineResponse])
def list_pipelines():
    return [PipelineResponse(**v) for v in PIPELINES.values()]


@app.post("/api/v1/pipelines", status_code=201, response_model=PipelineResponse)
def create_pipeline(req: PipelineCreateRequest):
    if req.pipeline_id in PIPELINES:
        raise HTTPException(status_code=409, detail="Pipeline already exists")

    missing = [s for s in req.sources if s not in SOURCES]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown sources: {missing}")

    PIPELINES[req.pipeline_id] = req.model_dump()
    return PipelineResponse(**PIPELINES[req.pipeline_id])


@app.put("/api/v1/pipelines/{pipeline_id}", response_model=PipelineResponse)
def update_pipeline(pipeline_id: str, req: PipelineUpdateRequest):
    pipeline = ensure_pipeline_exists(pipeline_id)

    if req.sources is not None:
        missing = [s for s in req.sources if s not in SOURCES]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown sources: {missing}")
        pipeline["sources"] = req.sources

    if req.target is not None:
        pipeline["target"] = req.target
    if req.schedule is not None:
        pipeline["schedule"] = req.schedule

    PIPELINES[pipeline_id] = pipeline
    return PipelineResponse(**pipeline)


@app.delete("/api/v1/pipelines/{pipeline_id}", status_code=204)
def delete_pipeline(pipeline_id: str):
    ensure_pipeline_exists(pipeline_id)
    del PIPELINES[pipeline_id]


# RUNS

@app.post("/api/v1/pipelines/{pipeline_id}/runs", status_code=202, response_model=RunResponse)
def start_pipeline_run(pipeline_id: str, req: RunCreateRequest):
    ensure_pipeline_exists(pipeline_id)

    run_id = f"run_{uuid4().hex[:12]}"
    started_at = now_iso()

    RUNS[run_id] = {
        "run_id": run_id,
        "pipeline_id": pipeline_id,
        "status": "success",
        "started_at": started_at,
        "finished_at": started_at,
        "params": req.params,
    }

    RUN_LOGS[run_id] = [
        f"[{started_at}] Run created",
        f"[{started_at}] Params: {req.params}",
        f"[{started_at}] ETL completed successfully",
    ]

    return RunResponse(**RUNS[run_id])


@app.get("/api/v1/runs/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str):
    run = ensure_run_exists(run_id)
    return RunStatusResponse(**run)


@app.get("/api/v1/runs/{run_id}/logs", response_model=RunLogsResponse)
def get_run_logs(run_id: str):
    ensure_run_exists(run_id)
    return RunLogsResponse(run_id=run_id, logs=RUN_LOGS.get(run_id, []))