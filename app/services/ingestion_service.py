import asyncio
import hashlib
import json
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zipfile import ZipFile

import httpx
from qdrant_client.http import models as rest

from app.core.config import settings
from app.db.postgres import get_pool, stable_uuid
from app.services.embedding_service import embedding_service
from app.services.retrieval_service import retrieval_service


XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_USER_AGENT = "Big_BaBon-ingester/1.0"


@dataclass
class IngestDocument:
    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def clean_text(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def normalize_condition(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.split(r"[,;/|]", str(value))
    return [str(item).strip().lower() for item in raw_values if str(item).strip()]


def token_estimate(text: str) -> int:
    return max(1, len(re.findall(r"\w+", text or "")))


def parse_key_value_metadata(items: list[str] | None) -> dict[str, str]:
    metadata = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"Metadata must be KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Metadata key cannot be empty: {item}")
        metadata[key] = value.strip()
    return metadata


class IngestionService:
    async def ingest_manifest(
        self,
        manifest_path: str,
        *,
        collection_name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        path = Path(manifest_path).expanduser().resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        defaults = data.get("defaults", {})
        sources = [source for source in data.get("sources", []) if source.get("enabled", True)]
        collection = collection_name or data.get("collection") or defaults.get("collection") or settings.QDRANT_COLLECTION

        job_id = await self.create_job(
            job_type="manifest",
            collection_name=collection,
            input_payload={"manifest_path": str(path), "source_count": len(sources), "dry_run": dry_run},
        )
        await self.mark_job_running(job_id)

        results = []
        try:
            for source in sources:
                result = await self.ingest_source(
                    source,
                    defaults=defaults,
                    collection_name=collection,
                    dry_run=dry_run,
                    parent_job_id=job_id,
                )
                results.append(result)
            summary = {
                "job_id": str(job_id),
                "status": "success",
                "source_count": len(sources),
                "chunk_count": sum(item.get("chunk_count", 0) for item in results),
                "results": results,
            }
            await self.mark_job_success(job_id, summary)
            return summary
        except Exception as exc:
            await self.mark_job_failed(job_id, exc)
            raise

    async def ingest_source(
        self,
        source: dict[str, Any],
        *,
        defaults: dict[str, Any] | None = None,
        collection_name: str | None = None,
        dry_run: bool = False,
        parent_job_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        defaults = defaults or {}
        source_id = source.get("id") or source.get("source_id")
        if not source_id:
            raw_source = source.get("url") or source.get("path") or source.get("file") or "source"
            source_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(str(raw_source)).stem or "source").strip("_")

        collection = collection_name or source.get("collection") or defaults.get("collection") or settings.QDRANT_COLLECTION
        job_id = parent_job_id or await self.create_job(
            job_type="source",
            collection_name=collection,
            source_id=source_id,
            input_payload={"source": source, "dry_run": dry_run},
        )
        if parent_job_id is None:
            await self.mark_job_running(job_id)

        try:
            documents = await self.load_source(source, defaults)
            chunk_size = int(source.get("chunk_size", defaults.get("chunk_size", DEFAULT_CHUNK_SIZE)))
            chunk_overlap = int(source.get("chunk_overlap", defaults.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP)))
            chunks = self.split_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap, source_id=source_id)

            full_text = "\n\n".join(doc.page_content for doc in documents)
            metadata = self.build_source_metadata(source, defaults)
            source_label = self.source_label(source)
            document_id = stable_uuid(source_id)
            await self.upsert_document_record(
                document_id=document_id,
                source_id=source_id,
                title=source.get("title") or metadata.get("title") or "",
                source=source_label,
                source_type=metadata.get("source_type", "kb"),
                collection_name=collection,
                checksum=sha256_text(full_text),
                status="dry_run" if dry_run else "running",
                metadata=metadata,
            )

            if dry_run:
                result = {
                    "source_id": source_id,
                    "document_id": str(document_id),
                    "status": "dry_run",
                    "document_count": len(documents),
                    "chunk_count": len(chunks),
                    "sample": clean_text(chunks[0].page_content)[:240] if chunks else "",
                }
                if parent_job_id is None:
                    await self.mark_job_success(job_id, result)
                return result

            await self.ensure_collection(collection, chunks)
            chunk_records = await self.upsert_chunks(collection, document_id, source_id, chunks)
            await self.set_document_status(document_id, "success")
            result = {
                "source_id": source_id,
                "document_id": str(document_id),
                "status": "success",
                "document_count": len(documents),
                "chunk_count": len(chunks),
                "qdrant_points": len(chunk_records),
            }
            if parent_job_id is None:
                await self.mark_job_success(job_id, result)
            return result
        except Exception as exc:
            if source_id:
                await self.set_document_status(stable_uuid(source_id), "failed")
            if parent_job_id is None:
                await self.mark_job_failed(job_id, exc)
            raise

    async def load_source(self, source: dict[str, Any], defaults: dict[str, Any]) -> list[IngestDocument]:
        metadata = self.build_source_metadata(source, defaults)
        title = source.get("title", "")
        url = source.get("url", "")
        path = source.get("path") or source.get("file")

        if url:
            docs = await self.load_url(url, source)
            source_label = url
        elif path:
            docs = self.load_local_file(path, source)
            source_label = str(Path(path).expanduser().resolve())
        else:
            raise ValueError("Source must have either path/file or url.")

        for index, doc in enumerate(docs):
            doc.metadata.update(metadata)
            doc.metadata.setdefault("source_id", source.get("id") or source.get("source_id"))
            doc.metadata.setdefault("title", title or doc.metadata.get("title") or doc.metadata.get("source", ""))
            doc.metadata.setdefault("source", source_label)
            if url:
                doc.metadata.setdefault("url", url)
            doc.metadata.setdefault("doc_index", index)
            if doc.metadata.get("condition"):
                doc.metadata["condition"] = normalize_condition(doc.metadata["condition"])
        return docs

    def build_source_metadata(self, source: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(defaults.get("metadata", {}))
        metadata.update(source.get("metadata", {}))
        metadata.setdefault("source_type", source.get("source_type", "kb"))
        metadata.setdefault("priority", source.get("priority", "medium"))
        metadata.setdefault("language", source.get("language", defaults.get("language", "vi")))
        if metadata.get("condition"):
            metadata["condition"] = normalize_condition(metadata["condition"])
        return metadata

    def source_label(self, source: dict[str, Any]) -> str:
        if source.get("url"):
            return str(source["url"])
        path = source.get("path") or source.get("file")
        return str(Path(path).expanduser().resolve()) if path else ""

    def load_local_file(self, file_path: str, source: dict[str, Any]) -> list[IngestDocument]:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        loader = source.get("loader", "")
        suffix = path.suffix.lower()
        if suffix == ".xlsx" or loader == "xlsx_food_table":
            return self.load_xlsx_food_table(path, source)
        if suffix == ".docx":
            return [IngestDocument(page_content=self.load_docx_text(path), metadata={"source": str(path)})]
        if suffix == ".pdf":
            return self.load_pdf(path)
        if suffix == ".txt":
            return [IngestDocument(page_content=clean_text(path.read_text(encoding=source.get("encoding", "utf-8"))), metadata={"source": str(path)})]
        raise ValueError(f"Unsupported file type: {suffix}. Use .docx, .pdf, .txt, or .xlsx.")

    async def load_url(self, url: str, source: dict[str, Any]) -> list[IngestDocument]:
        headers = {
            "User-Agent": source.get("user_agent", DEFAULT_USER_AGENT),
            "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=float(source.get("timeout", 30)), follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        is_pdf = "application/pdf" in content_type or urlparse(url).path.lower().endswith(".pdf")
        if is_pdf:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                temp_file.write(response.content)
                temp_path = Path(temp_file.name)
            try:
                return self.load_pdf(temp_path, source=url)
            finally:
                temp_path.unlink(missing_ok=True)

        text = self.html_to_text(response.text, selector=source.get("content_selector"))
        return [IngestDocument(page_content=text, metadata={"source": url, "url": url, "content_type": content_type})]

    def html_to_text(self, html: str, selector: str | None = None) -> str:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for element in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                element.decompose()
            candidates = []
            if selector:
                candidates.extend(soup.select(selector))
            candidates.extend(soup.select("article, [role='main'], main, #content, #main-content, .content, .main-content"))
            if soup.body:
                candidates.append(soup.body)
            candidates.append(soup)
            return max((clean_text(candidate.get_text("\n")) for candidate in candidates), key=len)
        except Exception:
            text = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.I | re.S)
            text = re.sub(r"<[^>]+>", " ", text)
            return clean_text(text)

    def load_docx_text(self, path: Path) -> str:
        with ZipFile(path) as zip_file:
            xml = zip_file.read("word/document.xml")
        root = ET.fromstring(xml)
        texts = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
        return clean_text("\n".join(texts))

    def load_pdf(self, path: Path, source: str | None = None) -> list[IngestDocument]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF ingest requires pypdf. Run: pip install pypdf") from exc

        reader = PdfReader(str(path))
        docs = []
        for index, page in enumerate(reader.pages):
            text = clean_text(page.extract_text() or "")
            if text:
                docs.append(IngestDocument(
                    page_content=text,
                    metadata={"source": source or str(path), "page": index + 1, "page_label": str(index + 1)},
                ))
        return docs

    def load_xlsx_food_table(self, path: Path, source: dict[str, Any]) -> list[IngestDocument]:
        rows = self.read_xlsx_rows(path)
        if not rows:
            return []

        headers = [self.normalize_header(value) for value in rows[0]]
        documents = []
        for row_index, row in enumerate(rows[1:], start=2):
            record = {
                headers[index]: row[index] if index < len(row) else ""
                for index in range(len(headers))
                if headers[index]
            }
            food_name = record.get("tên món ăn") or record.get("ten mon an") or f"Món #{row_index}"
            ingredients = record.get("tên nguyên liệu") or record.get("ten nguyen lieu") or ""
            unit = record.get("đơn vị") or record.get("don vi") or ""
            food_type = record.get("loại") or record.get("loai") or ""
            lines = [
                f"Tên món ăn: {food_name}",
                f"Nguyên liệu: {ingredients}",
                f"Đơn vị/khẩu phần: {unit}",
                f"Loại món: {food_type}",
                "Giá trị dinh dưỡng theo khẩu phần:",
            ]
            for label in ["tổng calo (kcal)", "protein (g)", "lipid (g)", "glucid (g)", "sắt (mg)", "kẽm (mg)", "natri (mg)"]:
                if record.get(label):
                    lines.append(f"- {label}: {record[label]}")
            metadata = {
                "title": f"{source.get('title', path.stem)} - {food_name}",
                "source": str(path),
                "food_name": food_name,
                "food_type": food_type,
                "row_index": row_index,
                "record_type": "food_nutrition",
                "split": False,
                **{f"food_{key}": value for key, value in record.items() if value},
            }
            documents.append(IngestDocument(page_content="\n".join(lines), metadata=metadata))
        return documents

    def read_xlsx_rows(self, path: Path) -> list[list[str]]:
        with ZipFile(path) as zip_file:
            shared_strings = self.read_shared_strings(zip_file)
            worksheet_path = self.first_worksheet_path(zip_file)
            root = ET.fromstring(zip_file.read(worksheet_path))

        rows = []
        for row in root.findall(".//a:sheetData/a:row", XLSX_NS):
            values_by_col = {}
            for cell in row.findall("a:c", XLSX_NS):
                ref = cell.attrib.get("r", "")
                col_num = self.column_number(ref)
                cell_type = cell.attrib.get("t", "")
                value = ""
                if cell_type == "inlineStr":
                    value = "".join(text.text or "" for text in cell.findall(".//a:t", XLSX_NS))
                else:
                    value_node = cell.find("a:v", XLSX_NS)
                    if value_node is not None and value_node.text is not None:
                        value = value_node.text
                        if cell_type == "s":
                            value = shared_strings[int(value)]
                values_by_col[col_num] = clean_text(value)
            if values_by_col:
                rows.append([values_by_col.get(index, "") for index in range(1, max(values_by_col) + 1)])
        return rows

    def read_shared_strings(self, zip_file: ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in zip_file.namelist():
            return []
        root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
        return ["".join(text.text or "" for text in item.findall(".//a:t", XLSX_NS)) for item in root.findall(".//a:si", XLSX_NS)]

    def first_worksheet_path(self, zip_file: ZipFile) -> str:
        workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
        first_sheet = workbook.find(".//a:sheet", XLSX_NS)
        if first_sheet is None:
            raise ValueError("XLSX workbook has no sheets.")
        rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rel_id:
            return "xl/worksheets/sheet1.xml"
        rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.findall(".//r:Relationship", REL_NS):
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib["Target"].lstrip("/")
                return target if target.startswith("xl/") else "xl/" + target
        return "xl/worksheets/sheet1.xml"

    def column_number(self, cell_ref: str) -> int:
        letters = "".join(ch for ch in cell_ref if ch.isalpha())
        number = 0
        for ch in letters.upper():
            number = number * 26 + ord(ch) - 64
        return number

    def normalize_header(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def split_documents(self, documents: list[IngestDocument], *, chunk_size: int, chunk_overlap: int, source_id: str) -> list[IngestDocument]:
        chunks = []
        for document in documents:
            if document.metadata.get("split") is False:
                chunks.append(document)
                continue
            text = clean_text(document.page_content)
            if not text:
                continue
            start = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                chunk_text = text[start:end].strip()
                if chunk_text:
                    chunks.append(IngestDocument(page_content=chunk_text, metadata=dict(document.metadata)))
                if end >= len(text):
                    break
                start = max(0, end - chunk_overlap)
        for index, chunk in enumerate(chunks):
            chunk.metadata["chunk_id"] = index
            chunk.metadata.setdefault("id", f"{source_id}:{index}")
        return chunks

    async def ensure_collection(self, collection_name: str, chunks: list[IngestDocument]) -> None:
        client = retrieval_service._get_client()
        try:
            await client.get_collection(collection_name)
        except Exception:
            if not chunks:
                raise
            vector = await embedding_service.embed(chunks[0].page_content)
            vectors_config = rest.VectorParams(size=len(vector), distance=rest.Distance.COSINE)
            if settings.QDRANT_VECTOR_NAME:
                vectors_config = {settings.QDRANT_VECTOR_NAME: vectors_config}
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
            )
        await self.ensure_payload_indexes(collection_name)

    async def ensure_payload_indexes(self, collection_name: str) -> None:
        client = retrieval_service._get_client()
        indexes = [
            ("metadata.source_type", rest.PayloadSchemaType.KEYWORD),
            ("metadata.risk_level", rest.PayloadSchemaType.KEYWORD),
            ("metadata.language", rest.PayloadSchemaType.KEYWORD),
            ("metadata.source", rest.PayloadSchemaType.KEYWORD),
            ("metadata.condition", rest.PayloadSchemaType.KEYWORD),
            ("metadata.title", rest.PayloadSchemaType.TEXT),
        ]
        for field_name, field_schema in indexes:
            try:
                await client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                )
            except Exception as exc:
                message = str(exc).lower()
                if "already exists" not in message and "index already" not in message:
                    raise

    async def upsert_chunks(
        self,
        collection_name: str,
        document_id: uuid.UUID,
        source_id: str,
        chunks: list[IngestDocument],
    ) -> list[dict[str, Any]]:
        client = retrieval_service._get_client()
        points = []
        records = []
        for chunk_index, chunk in enumerate(chunks):
            content_hash = sha256_text(chunk.page_content)
            point_id = stable_uuid(f"{collection_name}:{source_id}:{chunk_index}:{content_hash}")
            vector = await embedding_service.embed(chunk.page_content)
            point_vector = {settings.QDRANT_VECTOR_NAME: vector} if settings.QDRANT_VECTOR_NAME else vector
            metadata = dict(chunk.metadata)
            metadata.setdefault("source_id", source_id)
            metadata["chunk_id"] = chunk_index
            if metadata.get("condition"):
                metadata["condition"] = normalize_condition(metadata["condition"])
            payload = {"page_content": chunk.page_content, "metadata": metadata}
            points.append(rest.PointStruct(id=str(point_id), vector=point_vector, payload=payload))
            records.append({
                "id": stable_uuid(f"chunk:{point_id}"),
                "document_id": document_id,
                "chunk_index": chunk_index,
                "qdrant_point_id": point_id,
                "content_hash": content_hash,
                "char_count": len(chunk.page_content),
                "token_count": token_estimate(chunk.page_content),
                "metadata": metadata,
            })
        if points:
            await client.upsert(collection_name=collection_name, points=points)
            await self.replace_chunk_records(document_id, records)
        return records

    async def create_job(
        self,
        *,
        job_type: str,
        collection_name: str,
        input_payload: dict[str, Any],
        source_id: str | None = None,
    ) -> uuid.UUID:
        job_id = uuid.uuid4()
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ingest_jobs (id, job_type, status, collection_name, source_id, input)
                VALUES ($1, $2, 'pending', $3, $4, $5::jsonb)
                """,
                job_id,
                job_type,
                collection_name,
                source_id,
                json.dumps(input_payload, ensure_ascii=False),
            )
        return job_id

    async def mark_job_running(self, job_id: uuid.UUID) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE ingest_jobs SET status='running', started_at=NOW() WHERE id=$1", job_id)

    async def mark_job_success(self, job_id: uuid.UUID, result: dict[str, Any]) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE ingest_jobs SET status='success', result=$2::jsonb, completed_at=NOW() WHERE id=$1",
                job_id,
                json.dumps(result, ensure_ascii=False),
            )

    async def mark_job_failed(self, job_id: uuid.UUID, exc: Exception) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE ingest_jobs SET status='failed', error=$2, completed_at=NOW() WHERE id=$1",
                job_id,
                str(exc),
            )

    async def upsert_document_record(
        self,
        *,
        document_id: uuid.UUID,
        source_id: str,
        title: str,
        source: str,
        source_type: str,
        collection_name: str,
        checksum: str,
        status: str,
        metadata: dict[str, Any],
    ) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO documents (id, source_id, title, source, source_type, collection_name, checksum, status, metadata, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,NOW())
                ON CONFLICT (source_id) DO UPDATE SET
                    title=EXCLUDED.title,
                    source=EXCLUDED.source,
                    source_type=EXCLUDED.source_type,
                    collection_name=EXCLUDED.collection_name,
                    checksum=EXCLUDED.checksum,
                    status=EXCLUDED.status,
                    metadata=EXCLUDED.metadata,
                    updated_at=NOW()
                """,
                document_id,
                source_id,
                title,
                source,
                source_type,
                collection_name,
                checksum,
                status,
                json.dumps(metadata, ensure_ascii=False),
            )

    async def set_document_status(self, document_id: uuid.UUID, status: str) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE documents SET status=$2, updated_at=NOW() WHERE id=$1", document_id, status)

    async def replace_chunk_records(self, document_id: uuid.UUID, records: list[dict[str, Any]]) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM document_chunks WHERE document_id=$1", document_id)
                for record in records:
                    await conn.execute(
                        """
                        INSERT INTO document_chunks
                            (id, document_id, chunk_index, qdrant_point_id, content_hash, char_count, token_count, metadata)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                        """,
                        record["id"],
                        record["document_id"],
                        record["chunk_index"],
                        record["qdrant_point_id"],
                        record["content_hash"],
                        record["char_count"],
                        record["token_count"],
                        json.dumps(record["metadata"], ensure_ascii=False),
                    )


ingestion_service = IngestionService()


def run_async(coro):
    return asyncio.run(coro)
