"""
Gradio UI cho Big BaBon — public-share được qua share=True.

Kiến trúc: Gradio = frontend thuần, CHỈ gọi API FastAPI backend qua HTTP.
Không import package `app` -> chạy được trong venv riêng (chỉ cần gradio + httpx),
tránh xung đột huggingface-hub giữa gradio và transformers của backend.

Mỗi phiên trình duyệt tự đăng ký 1 tài khoản guest qua /v1/auth/register ->
nhận token + dùng session_id riêng -> không đụng dữ liệu nhau, persist DB đúng FK.

Chạy:
    1. Bật backend trước (venv backend): uvicorn app.main:app --port 8000
    2. python gradio_app.py (venv ui)
    -> in ra public URL *.gradio.live (sống ~72h)

Đổi backend khác: set env BABON_API_URL=http://host:port
Gate truy cập public bằng user/pass: set env GRADIO_AUTH="user:pass"
"""
import os
import uuid

import gradio as gr
import httpx

API_URL = os.environ.get("BABON_API_URL", "http://localhost:8000").rstrip("/")


def _new_session() -> dict:
    # Đăng ký 1 guest account qua API -> token. Username + password ngẫu nhiên/duy nhất.
    guest_id = "guest-" + uuid.uuid4().hex[:12]
    resp = httpx.post(
        f"{API_URL}/v1/auth/register",
        json={"username": guest_id, "password": uuid.uuid4().hex},
        timeout=30,
    )
    resp.raise_for_status()
    return {
        "token": resp.json()["access_token"],
        "session_id": "sess-" + uuid.uuid4().hex[:12],
    }


def respond(message: str, history: list, sess: dict | None):
    message = (message or "").strip()
    if not message:
        return history, sess, ""

    try:
        if not sess:
            sess = _new_session()
        resp = httpx.post(
            f"{API_URL}/v1/chat",
            headers={"Authorization": f"Bearer {sess['token']}"},
            json={"session_id": sess["session_id"], "message": message},
            timeout=120,
        )
        if resp.status_code != 200:
            answer = f"[Lỗi {resp.status_code}] {resp.text[:300]}"
        else:
            data = resp.json()
            answer = data.get("answer") or "(không có nội dung)"
            cites = data.get("citations") or []
            if cites:
                names = ", ".join(str(c.get("title") or c.get("source") or "?") for c in cites)
                answer += f"\n\n_Nguồn: {names}_"
    except httpx.HTTPError as exc:
        answer = f"[Không gọi được backend tại {API_URL}: {type(exc).__name__}]"

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]
    return history, sess, ""


with gr.Blocks(title="Big BaBon Chat", fill_height=True) as demo:
    gr.Markdown("## Big BaBon — RAG chatbot tiếng Việt")
    sess_state = gr.State()
    chatbot = gr.Chatbot(height=480, show_label=False)
    with gr.Row():
        msg = gr.Textbox(placeholder="Nhập tin nhắn...", show_label=False, scale=8, autofocus=True)
        send = gr.Button("Gửi", variant="primary", scale=1)

    inputs = [msg, chatbot, sess_state]
    outputs = [chatbot, sess_state, msg]
    msg.submit(respond, inputs, outputs)
    send.click(respond, inputs, outputs)


if __name__ == "__main__":
    auth_env = os.environ.get("GRADIO_AUTH")  # "user:pass" -> bật cổng đăng nhập Gradio
    auth = tuple(auth_env.split(":", 1)) if auth_env and ":" in auth_env else None
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("GRADIO_PORT", "7860")),
        share=True,
        auth=auth,
    )
