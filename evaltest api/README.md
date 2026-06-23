# Evaltest API

## Cấu trúc

- `cases/`: bộ test JSONL.
- `results/`: kết quả từng case và metrics JSON.
- `reports/`: báo cáo đọc nhanh.
- `logs/`: log các lần chạy API trước.

## Bộ smalltalk → RAG

`cases/smalltalk_to_rag_40.jsonl` gồm 10 user, mỗi user 4 lượt:

1. Smalltalk mở đầu.
2. RAG thiết lập chủ đề.
3. RAG follow-up cần nhớ ngữ cảnh.
4. RAG follow-up/tóm tắt cần nhớ toàn chuỗi.

Chạy lại:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_api.py `
  --cases "evaltest api\cases\smalltalk_to_rag_40.jsonl" `
  --output "evaltest api\results\smalltalk_to_rag_40_results.jsonl" `
  --summary-output "evaltest api\results\smalltalk_to_rag_40_summary.json" `
  --run-id your-unique-run-id `
  --timeout 180
```
