import os
from pathlib import Path

from login import LoginResult, login


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def main() -> None:
    load_dotenv()

    account = os.getenv("CREALITY_ACCOUNT")
    password = os.getenv("CREALITY_PASSWORD")

    if not account or not password:
        raise SystemExit("Configura CREALITY_ACCOUNT y CREALITY_PASSWORD (en .env o entorno) antes de ejecutar.")

    result: LoginResult = login(account, password)

    print("Login correcto en Creality Cloud.")
    print(f"user_id: {result.user_id}")
    print(f"oauth_code: {result.oauth_code}")
    if result.model_token:
        print(f"model_token: {result.model_token}")
    else:
        print(f"token id.creality: {result.token}")


if __name__ == "__main__":
    main()
