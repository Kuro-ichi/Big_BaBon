# Big BaBon API

API chatbot RAG tiếng Việt sử dụng FastAPI, PostgreSQL, Redis, Qdrant và Ollama. Hệ thống hỗ trợ dense retrieval, BM25 sparse retrieval, RRF, rerank, session memory, JWT authentication và streaming SSE.

## Yêu cầu

- Python 3.11+
- PostgreSQL
- Redis
- Qdrant
- Ollama
- Docker Desktop (nếu chạy Redis hoặc toàn bộ hệ thống bằng Docker)

## 1. Cấu hình môi trường

Tạo hoặc cập nhật file `.env` tại thư mục gốc:

```env
APP_ENV=development

DATABASE_URL=postgresql://chatbot:chatbot@localhost:5432/chatbotdb
DOCKER_DATABASE_URL=postgresql://chatbot:chatbot@host.docker.internal:5432/chatbotdb

REDIS_URL=redis://localhost:6379/0
REDIS_CONNECT_TIMEOUT=1
REDIS_SOCKET_TIMEOUT=1

QDRANT_URL=https://your-qdrant-endpoint
QDRANT_API_KEY=your-qdrant-api-key
QDRANT_COLLECTION=doc_store
QDRANT_VECTOR_NAME=
QDRANT_PAYLOAD_TEXT=text
QDRANT_PAYLOAD_SOURCE=source

EMBEDDING_MODEL=keepitreal/vietnamese-sbert

LLM_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
DOCKER_OLLAMA_URL=http://host.docker.internal:11434
LLM_MODEL_LIGHT=qwen2.5:3b
LLM_MODEL_HEAVY=qwen2.5:7b
LLM_MODEL_ROUTER=qwen2.5:3b
LLM_TIMEOUT=30
LLM_ROUTER_TIMEOUT=8
LLM_ANSWER_TIMEOUT=30
ROUTER_RISK_OVERRIDE_CONFIDENCE=0.65

QDRANT_TIMEOUT=10
DATABASE_CONNECT_TIMEOUT=5
RETRIEVAL_CONTEXT_MAX_TOKENS=2200
RETRIEVAL_MAX_DOCUMENTS=8
RETRIEVAL_MIN_RERANK_SCORE=-0.2
KEYWORD_SCROLL_MAX_POINTS=2048

WEB_FALLBACK_ENABLED=false
WORKER_TASKS_ENABLED=false
API_HOST=0.0.0.0
API_PORT=8000

AUTH_REQUIRED=true
JWT_SECRET=replace-with-a-random-secret-at-least-32-characters
JWT_ISSUER=big-babon-api
JWT_AUDIENCE=big-babon-clients
JWT_ACCESS_TOKEN_MINUTES=1440

Không commit hoặc chia sẻ file `.env`.

## 2. Cài dependencies

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 3. Khởi động dịch vụ phụ thuộc

Khởi động Redis:

```powershell
docker compose up -d redis
```

Cài model Ollama:

```powershell
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
```

Khởi động Ollama nếu ứng dụng Ollama chưa chạy:

```powershell
ollama serve
```

PostgreSQL và Qdrant phải truy cập được bằng cấu hình trong `.env`.

## 4. Khởi tạo PostgreSQL

```powershell
.\.venv\Scripts\python.exe scripts\apply_schema.py
```

Lệnh sử dụng `CREATE TABLE/INDEX IF NOT EXISTS` và không xóa dữ liệu hiện tại.

## 5. Chạy API

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Các endpoint kiểm tra:

- `GET /health/live`: tiến trình API còn hoạt động.
- `GET /health/ready`: kiểm tra PostgreSQL, Redis, Qdrant, Ollama và cấu hình authentication.
- `GET /docs`: Swagger UI.

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
```

Chỉ phục vụ request khi readiness trả HTTP `200` và `status: ready`.

## 6. Tạo Bearer token

```powershell
.\.venv\Scripts\python.exe scripts\create_access_token.py `
  --user-id demo-user `
  --minutes 120
```

Mỗi người dùng hoặc máy khách nên có `user-id` riêng. API lấy danh tính từ JWT và không tin `user_id` trong request body.

## 7. Gọi Chat API

```powershell
$token = "PASTE_TOKEN_HERE"

$body = @{
    session_id = "demo-session-01"
    message = "Người bị tiểu đường nên ăn gì?"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://localhost:8000/v1/chat" `
  -Method Post `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body $body
```

Một session chỉ thuộc một user. Token của user khác truy cập cùng `session_id` sẽ nhận HTTP `403`.

## 8. Streaming SSE

```powershell
$payload = '{"session_id":"demo-stream-01","message":"Gợi ý một bữa sáng phù hợp"}'

curl.exe -N `
  -X POST "http://localhost:8000/v1/chat/stream" `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d $payload
```

Response nhạy cảm được buffer cho tới khi qua output guard trước khi gửi cho client.

## 9. Truy cập từ máy khác trong LAN

Lấy IPv4 của máy chạy API:

```powershell
ipconfig
```

Mở PowerShell với quyền Administrator và cho phép cổng API trên mạng Private:

```powershell
New-NetFirewallRule `
  -DisplayName "BigBaBon API 8000" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8000 `
  -Action Allow `
  -Profile Private
```

Máy khác trong LAN sử dụng địa chỉ dạng:

```text
http://192.168.1.20:8000/docs
```

Không mở trực tiếp cổng HTTP 8000 ra Internet. Nếu cần truy cập ngoài LAN, hãy đặt API sau HTTPS hoặc VPN.

## 10. Chạy test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Scripts vận hành

- `scripts/apply_schema.py`: tạo bảng và index PostgreSQL.
- `scripts/create_access_token.py`: tạo JWT cho client.
- `scripts/create_qdrant_payload_indexes.py`: tạo payload index Qdrant.
- `scripts/ingest_manifest.py`: ingest tài liệu vào knowledge base.

## Lưu ý bảo mật

- Không sử dụng `JWT_SECRET=change-me`.
- Không gửi token trong URL; luôn dùng header `Authorization: Bearer ...`.
- Không chia sẻ token giữa nhiều user.
- Chỉ mở firewall cho mạng Private cần thiết.
- Kiểm tra `/health/ready` trước khi demo hoặc deploy.
