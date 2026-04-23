from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from backend.precheck import normalize_domain
from backend.schemas import FeedbackEvent, ScanRecord, TrustedDomainRecord, Verdict


class JsonRepository:
    def __init__(self, path: str | Path = "data/phishguard_store.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        if not self.path.exists():
            self._write({"scans": [], "feedback": [], "trusted_domains": []})

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read(self) -> dict:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, data: dict) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    @staticmethod
    def _dump(model):
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()

    @staticmethod
    def _validate(model_cls, payload):
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(payload)
        return model_cls.parse_obj(payload)

    def upsert_scan(self, record: ScanRecord) -> None:
        payload = self._dump(record)
        with self._lock:
            data = self._read()
            data["scans"] = [item for item in data["scans"] if item["scan_id"] != record.scan_id]
            data["scans"].insert(0, payload)
            self._write(data)

    def get_scan(self, scan_id: str) -> ScanRecord | None:
        with self._lock:
            data = self._read()
        for item in data["scans"]:
            if item["scan_id"] == scan_id:
                return self._validate(ScanRecord, item)
        return None

    def find_scan_by_url(self, url: str, device_id: str | None = None) -> ScanRecord | None:
        with self._lock:
            data = self._read()
        for item in data["scans"]:
            if item["url"] != url:
                continue
            if device_id and item.get("device_id") != device_id:
                continue
            return self._validate(ScanRecord, item)
        return None

    def list_scans(
        self,
        *,
        device_id: str | None = None,
        verdict: Verdict | None = None,
        limit: int = 200,
    ) -> list[ScanRecord]:
        with self._lock:
            data = self._read()
        items = []
        for raw in data["scans"]:
            if device_id and raw.get("device_id") != device_id:
                continue
            if verdict and raw.get("verdict") != verdict:
                continue
            items.append(self._validate(ScanRecord, raw))
            if len(items) >= limit:
                break
        return items

    def add_feedback(self, event: FeedbackEvent) -> None:
        payload = self._dump(event)
        with self._lock:
            data = self._read()
            data["feedback"].insert(0, payload)
            self._write(data)

    def list_feedback(self, device_id: str | None = None) -> list[FeedbackEvent]:
        with self._lock:
            data = self._read()
        items = []
        for raw in data["feedback"]:
            if device_id and raw.get("device_id") != device_id:
                continue
            items.append(self._validate(FeedbackEvent, raw))
        return items

    def upsert_trusted_domain(self, record: TrustedDomainRecord) -> None:
        payload = self._dump(record)
        payload["domain"] = normalize_domain(payload["domain"])
        with self._lock:
            data = self._read()
            data["trusted_domains"] = [
                item
                for item in data["trusted_domains"]
                if not (
                    item["domain"] == payload["domain"]
                    and item.get("device_id") == payload.get("device_id")
                )
            ]
            data["trusted_domains"].insert(0, payload)
            self._write(data)

    def remove_trusted_domain(self, *, domain: str, device_id: str | None = None) -> bool:
        normalized = normalize_domain(domain)
        removed = False
        with self._lock:
            data = self._read()
            updated = []
            for item in data["trusted_domains"]:
                matches_domain = item["domain"] == normalized
                matches_device = device_id is None or item.get("device_id") == device_id
                if matches_domain and matches_device:
                    removed = True
                    continue
                updated.append(item)
            data["trusted_domains"] = updated
            self._write(data)
        return removed

    def list_trusted_domains(self, device_id: str | None = None) -> list[TrustedDomainRecord]:
        with self._lock:
            data = self._read()
        items = []
        for raw in data["trusted_domains"]:
            if device_id and raw.get("device_id") != device_id:
                continue
            items.append(self._validate(TrustedDomainRecord, raw))
        return items

    def list_trusted_domain_values(self, device_id: str | None = None) -> list[str]:
        return [item.domain for item in self.list_trusted_domains(device_id=device_id)]
