"""Terminal REPL để test chatbot tại local — gọi thẳng LangGraph, không cần API.

Chạy:  python chat_cli.py
Thoát: gõ 'exit' / 'quit' / Ctrl+C
"""
import asyncio
import sys
import uuid

# Console Windows mặc định cp1252 -> ép UTF-8 để in tiếng Việt không crash
sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from app.schemas.chat_schema import ChatRequest
from app.services.chat_service import ChatService


async def main():
    service = ChatService()
    user_id = "local-user"
    session_id = str(uuid.uuid4())  # 1 phiên / 1 lần chạy

    print("=" * 60)
    print(" Chatbot local REPL  (gõ 'exit' để thoát)")
    print(f" session_id = {session_id}")
    print("=" * 60)

    while True:
        try:
            message = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not message:
            continue
        if message.lower() in {"exit", "quit", ":q"}:
            print("Bye.")
            break

        request = ChatRequest(user_id=user_id, session_id=session_id, message=message)
        result = await service.chat(request)

        print(f"\nBot> {result['answer']}")
        print(
            f"     [route={result['route']} "
            f"confidence={result['confidence']} "
            f"citations={len(result['citations'])}]"
        )


if __name__ == "__main__":
    asyncio.run(main())
