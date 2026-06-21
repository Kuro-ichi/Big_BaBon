# Mixed retrieval + RAG + smalltalk (24 cases)

Ngày chạy: 2026-06-19  
Thiết kế: 6 user × 4 lượt: smalltalk → retrieval → RAG → RAG context.

## Bản rebuild ban đầu

- Pass: 9/24 (37,5%).
- Route accuracy: 24/24.
- Context content recall: 10/12 (83,33%).
- Confidence chỉ đạt 9/24 vì hệ thống dùng RRF score thô (~0,03).
- Safety fast-path CKD bị output guard xóa nhầm.

## Các lỗi đã sửa

1. `rerank_trim` ghi selected documents/score sau rerank trở lại state trước khi tính confidence.
2. Curated safety fast-path không bị matcher từ khóa quét và thay thế lần hai.
3. Follow-up kế thừa `safety_guardrail` hoặc `food_composition_table` từ citations của lượt trước.
4. Prompt RAG cấm chữ Trung/Cyrillic; evaluator kiểm tra cả hai script.

## Kết quả sau sửa và rebuild

| Metric | Kết quả |
|---|---:|
| HTTP 200 | 24/24 (100%) |
| Pass raw | 21/24 (87,5%) |
| Route accuracy | 23/24 (95,83%) |
| Confidence đạt ngưỡng | 24/24 (100%) |
| Citation đạt ngưỡng | 23/24 (95,83%) |
| Source type đúng | 17/18 (94,44%) |
| Must-include | 17/18 (94,44%) |
| Không có foreign script | 24/24 (100%) |
| Context content recall | 11/12 (91,67%) |
| Context full-case pass | 10/12 (83,33%) |
| Latency trung bình / P95 | 17,012s / 37,587s |

## Ba case raw còn fail

- `MIX_U01_T2`: Ollama heavy model timeout (`[LLM error]`) ở lượt retrieval đầu tiên.
- `MIX_U01_T4`: router chọn `direct_answer` thay vì tiếp tục RAG; đã bổ sung ép route RAG khi follow-up có prior citations.
- `MIX_U04_T3`: evaluator cũ bắt nhầm cụm an toàn “không nên uống nhiều”; test case đã đổi forbidden phrase thành khẳng định nguy hiểm đầy đủ.

Hai lỗi logic cuối đã sửa sau lần chạy raw. Lần chạy tiếp theo với run-id mới sẽ phản ánh các chỉnh sửa này.
