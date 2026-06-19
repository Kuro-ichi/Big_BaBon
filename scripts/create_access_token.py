import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.auth_service import create_access_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a signed API Bearer token.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--minutes", type=int, default=None)
    args = parser.parse_args()
    print(create_access_token(args.user_id, args.minutes))


if __name__ == "__main__":
    main()
