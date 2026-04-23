from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.precheck import run_stage1_precheck
from backend.schemas import (
    FeedbackEvent,
    FeedbackRequest,
    HistoryResponse,
    PrecheckRequest,
    PrecheckResponse,
    ScanRecord,
    ScanRequest,
    ScanResponse,
    StageVerdict,
    TrustedDomainRecord,
    TrustedDomainRequest,
    Verdict,
    WhitelistResponse,
)
from backend.signals import (
    build_grouped_signals,
    build_recommendation,
    derive_verdict,
    resolve_consistency,
)
from backend.store import JsonRepository
from ml.inference import InferenceArtifacts, load_artifacts, predict_url

artifacts: InferenceArtifacts | None = None
repository = JsonRepository()

MAX_TEXT_CLEAN_CHARS = 12_000
MAX_TEXT_RAW_CHARS = 60_000


def clean_html(html_content: str) -> str:
    if not html_content or not isinstance(html_content, str):
        return ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "meta", "noscript"]):
            tag.extract()
        text = soup.get_text(separator=" ")
        return " ".join(text.split())
    except Exception:
        return ""


def normalize_text_payload(title: str, text_clean: str, text_raw: str) -> tuple[str, str]:
    safe_raw = (text_raw or "")[:MAX_TEXT_RAW_CHARS]
    clean = (text_clean or "").strip()
    if not clean and safe_raw:
        clean = clean_html(safe_raw)
    if title and title.strip():
        title_value = title.strip()
        if title_value.lower() not in clean.lower():
            clean = f"{title_value}\n{clean}".strip()
    return clean[:MAX_TEXT_CLEAN_CHARS], safe_raw


def build_scan_record(scan_request: ScanRequest, *, persist: bool = True) -> ScanRecord:
    if artifacts is None:
        raise RuntimeError("Inference artifacts are not loaded.")

    trusted_domains = repository.list_trusted_domain_values(scan_request.device_id)
    stage1 = run_stage1_precheck(
        url=scan_request.url,
        trusted_domains=trusted_domains,
        safeguard=artifacts.safeguard,
    )
    text_clean, text_raw = normalize_text_payload(
        title=scan_request.title,
        text_clean=scan_request.text_clean,
        text_raw=scan_request.text_raw,
    )
    inference = predict_url(
        url=scan_request.url,
        text_clean=text_clean,
        text_raw=text_raw,
        artifacts=artifacts,
    )
    preliminary_stage2_verdict: StageVerdict = derive_verdict(
        final_score=float(inference["final_score"]),
        threshold=float(inference["threshold"]),
        filter_reason=str(inference["filter_reason"]),
    )
    evidence_signals = build_grouped_signals(
        url=scan_request.url,
        text_clean=text_clean,
        text_raw=text_raw,
        filter_reason=str(inference["filter_reason"]),
        final_score=float(inference["final_score"]),
        threshold=float(inference["threshold"]),
        verdict=preliminary_stage2_verdict,
    )
    stage2_verdict: StageVerdict = derive_verdict(
        final_score=float(inference["final_score"]),
        threshold=float(inference["threshold"]),
        filter_reason=str(inference["filter_reason"]),
        grouped_signals=evidence_signals,
    )
    verdict, consistency_status, consistency_reason = resolve_consistency(
        stage1_verdict=stage1.stage1_verdict,
        stage2_verdict=stage2_verdict,
        stage1_reason=stage1.reason,
    )
    grouped_signals = build_grouped_signals(
        url=scan_request.url,
        text_clean=text_clean,
        text_raw=text_raw,
        filter_reason=str(inference["filter_reason"]),
        final_score=float(inference["final_score"]),
        threshold=float(inference["threshold"]),
        verdict=stage2_verdict,
        consistency_status=consistency_status,
        stage1_verdict=stage1.stage1_verdict,
        stage2_verdict=stage2_verdict,
    )
    record = ScanRecord(
        scan_id=str(uuid4()),
        url=scan_request.url,
        title=scan_request.title,
        verdict=verdict,
        stage1_verdict=stage1.stage1_verdict,
        stage1_score=stage1.stage1_score,
        stage1_reason=stage1.reason,
        stage2_verdict=stage2_verdict,
        consistency_status=consistency_status,
        consistency_reason=consistency_reason,
        raw_score=float(inference["raw_score"]),
        calibrated_score=float(inference["calibrated_score"]),
        final_score=float(inference["final_score"]),
        threshold=float(inference["threshold"]),
        signals=grouped_signals,
        filter_reason=str(inference["filter_reason"]),
        recommendation=build_recommendation(
            verdict,
            str(inference["filter_reason"]),
            consistency_status=consistency_status,
        ),
        timestamp=repository.now_iso(),
        architecture="non_visual_multimodal_fusion",
        source=scan_request.source,
        device_id=scan_request.device_id,
        tab_id=scan_request.tab_id,
    )
    if persist:
        repository.upsert_scan(record)
    return record


@asynccontextmanager
async def lifespan(_: FastAPI):
    global artifacts
    artifacts = load_artifacts()
    yield


app = FastAPI(title="PhishGuard Non-Visual API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict[str, Any]:
    return {
        "status": "ok",
        "architecture": "non_visual_multimodal_fusion",
        "model_loaded": artifacts is not None,
    }


@app.post("/v1/precheck", response_model=PrecheckResponse)
def precheck(payload: PrecheckRequest) -> PrecheckResponse:
    trusted_domains = repository.list_trusted_domain_values(payload.device_id)
    return run_stage1_precheck(
        url=payload.url,
        trusted_domains=trusted_domains,
        safeguard=artifacts.safeguard if artifacts else None,
    )


@app.post("/v1/scan", response_model=ScanResponse)
def scan(payload: ScanRequest) -> ScanResponse:
    return build_scan_record(payload, persist=True)


@app.post("/v1/feedback", response_model=FeedbackEvent)
def submit_feedback(payload: FeedbackRequest) -> FeedbackEvent:
    event = FeedbackEvent(
        feedback_id=str(uuid4()),
        scan_id=payload.scan_id,
        url=payload.url,
        user_action=payload.user_action,
        previous_verdict=payload.previous_verdict,
        notes=payload.notes,
        timestamp=payload.timestamp or repository.now_iso(),
        source=payload.source,
        device_id=payload.device_id,
        sync_status="synced",
    )
    repository.add_feedback(event)
    return event


@app.get("/v1/report/{scan_id}", response_model=ScanRecord)
def get_report(scan_id: str) -> ScanRecord:
    record = repository.get_scan(scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scan report not found.")
    return record


@app.get("/v1/report/by-url", response_model=ScanRecord)
def get_report_by_url(
    url: str = Query(...),
    device_id: str | None = Query(default=None),
) -> ScanRecord:
    record = repository.find_scan_by_url(url=url, device_id=device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scan report not found for URL.")
    return record


@app.get("/v1/history", response_model=HistoryResponse)
def get_history(
    device_id: str | None = Query(default=None),
    verdict: Verdict | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> HistoryResponse:
    items = repository.list_scans(device_id=device_id, verdict=verdict, limit=limit)
    return HistoryResponse(items=items)


@app.get("/v1/feedback", response_model=list[FeedbackEvent])
def get_feedback(device_id: str | None = Query(default=None)) -> list[FeedbackEvent]:
    return repository.list_feedback(device_id=device_id)


@app.post("/v1/whitelist", response_model=TrustedDomainRecord)
def add_whitelist_entry(payload: TrustedDomainRequest) -> TrustedDomainRecord:
    record = TrustedDomainRecord(
        domain=payload.domain,
        device_id=payload.device_id,
        added_at=repository.now_iso(),
        source=payload.source,
        note=payload.note,
    )
    repository.upsert_trusted_domain(record)
    return record


@app.delete("/v1/whitelist/{domain}")
def delete_whitelist_entry(
    domain: str,
    device_id: str | None = Query(default=None),
) -> dict[str, str]:
    removed = repository.remove_trusted_domain(domain=domain, device_id=device_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Trusted domain not found.")
    return {"status": "deleted", "domain": domain}


@app.get("/v1/whitelist", response_model=WhitelistResponse)
def get_whitelist(device_id: str | None = Query(default=None)) -> WhitelistResponse:
    return WhitelistResponse(items=repository.list_trusted_domains(device_id=device_id))


@app.options("/predict")
def options_predict() -> JSONResponse:
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.post("/predict")
async def legacy_predict(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        scan_request = ScanRequest(
            url=payload.get("url", ""),
            title=payload.get("title", ""),
            text_clean="",
            text_raw=payload.get("html_content", ""),
            source="legacy_predict",
        )
        result = build_scan_record(scan_request, persist=False)
        return JSONResponse(
            content={
                "status": "PHISHING" if result.verdict == "malicious" else "LEGITIMATE",
                "confidence": result.final_score,
                "url": result.url,
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception as exc:
        return JSONResponse(
            content={"error": str(exc)},
            status_code=500,
            headers={"Access-Control-Allow-Origin": "*"},
        )
