import json
import os
import time
from dataclasses import dataclass
from uuid import uuid4
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import requests

ID_BASE_URL = "https://id.creality.com"
CLOUD_BASE_URL = "https://www.crealitycloud.com"
DEFAULT_CLIENT_ID = os.getenv("CREALITY_CLIENT_ID", "f9c302ecc29c59a0a6e921ff39a073ca")
USER_AGENT = os.getenv(
    "CREALITY_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
)


@dataclass
class LoginResult:
    session: requests.Session
    token: str
    user_id: str
    oauth_code: str
    model_token: Optional[str]
    model_user_id: Optional[str]


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": USER_AGENT,
            "__cxy_app_id_": "creality_model",
            "__cxy_platform_": "2",
            "__cxy_os_lang_": "7",
            "__cxy_timezone_": "3600",
            "__cxy_app_ver_": "0.0.1",
            "__cxy_app_ch_": "Chrome 142.0.0.0",
            "__cxy_os_ver_": "Windows 10",
            "Accept-Language": "es-ES,es;q=0.9",
            "Origin": ID_BASE_URL,
            "Referer": f"{ID_BASE_URL}/",
        }
    )
    # Cookies que el backend suele esperar
    session.cookies.set("id-app-id", "creality_model", domain="id.creality.com")
    session.cookies.set("id-lang", "7", domain="id.creality.com")
    session.cookies.set("id-locale", "es-ES", domain="id.creality.com")

    # Identificadores de dispositivo minimos
    duid = os.getenv("CREALITY_DUID", str(uuid4()))
    session.headers["__cxy_duid_"] = duid
    session.cookies.set("id-uuid", duid, domain="id.creality.com")

    return session


def _parse_id_application_cookie(cookie_value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not cookie_value:
        return None, None
    try:
        decoded = unquote(cookie_value)
        payload = json.loads(decoded)
        return payload.get("token"), str(payload.get("userId") or "")
    except (json.JSONDecodeError, TypeError):
        return None, None


def _extract_token_and_user(body: object) -> Tuple[Optional[str], str]:
    token: Optional[str] = None
    user_id: str = ""

    def walk(node: object) -> None:
        nonlocal token, user_id
        if isinstance(node, dict):
            for key, value in node.items():
                lower = key.lower()
                if token is None and lower in {"token", "access_token", "id-token"} and isinstance(value, str):
                    token = value
                if not user_id and lower in {"userid", "user_id", "uid"}:
                    user_id = str(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    return token, user_id


def _post_credentials(
    session: requests.Session, account: str, password: str, platform: int, timeout: int
) -> Tuple[str, str]:
    request_id = str(uuid4())
    session.headers["__cxy_requestid_"] = request_id

    payload = {
        "type": 2,
        "account": account,
        "password": password,
        "appId": "creality_model",
        "clientId": DEFAULT_CLIENT_ID,
        "lang": 7,
        "locale": "es-ES",
        "countryCode": "",
        "platform": platform,
        "timezone": 3600,
    }
    
    response = session.post(f"{ID_BASE_URL}/api/cxy/account/v2/loginV2", json=payload, timeout=timeout)
    response.raise_for_status()

    token: Optional[str] = None
    user_id: str = ""

    try:
        body = response.json()
    except ValueError:
        body = {}

    if isinstance(body, dict):
        data = body.get("data") or {}
        token = data.get("token") or body.get("token")
        user_id = str(data.get("userId") or body.get("userId") or "")
        if token is None:
            nested_token, nested_user = _extract_token_and_user(body)
            token = nested_token
            user_id = user_id or nested_user

    cookie_token, cookie_user_id = _parse_id_application_cookie(session.cookies.get("id-application"))
    cookie_token = cookie_token or session.cookies.get("__cxy_token_")
    cookie_user_id = cookie_user_id or session.cookies.get("__cxy_uid_")
    token = token or cookie_token
    user_id = user_id or (cookie_user_id or "")

    if not token:
        detail = ""
        if isinstance(body, dict):
            code = body.get("code")
            msg = body.get("msg") or body.get("message")
            detail = f" code={code!r} msg={msg!r} keys={list(body.keys())}"
        else:
            detail = f" raw_body={str(body)[:200]}"
        detail += f" http_status={response.status_code}"
        detail += f" text_snippet={response.text[:200]!r}"
        raise RuntimeError("No se pudo extraer el token de login de id.creality.com." + detail)
    return token, user_id


def _authorize_code(
    session: requests.Session,
    token: str,
    user_id: str,
    client_id: str,
    redirect_uri: str,
    platform: int,
    timeout: int,
) -> str:
    headers = {"__cxy_token_": token, "__cxy_uid_": str(user_id)}
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "timestamp": int(time.time() * 1000),
        "platform": platform,
    }

    response = session.get(
        f"{ID_BASE_URL}/api/cxy/oauth2/authorize", params=params, headers=headers, timeout=timeout
    )
    response.raise_for_status()

    code: Optional[str] = None
    try:
        body = response.json()
        # Buscar código en diferentes ubicaciones posibles
        code = body.get("data", {}).get("code") or body.get("code")
        
        # Si no está en data/code, buscar en result.location
        if not code and body.get("result", {}).get("location"):
            location_url = body["result"]["location"]
            parsed = urlparse(location_url)
            code = parse_qs(parsed.query).get("code", [None])[0]
            
    except ValueError:
        pass

    if not code:
        parsed = urlparse(response.url)
        code = parse_qs(parsed.query).get("code", [None])[0]

    if not code:
        raise RuntimeError("La autorizacion no devolvio codigo OAuth.")
    return code


def _exchange_code_for_token(
    session: requests.Session, code: str, redirect_uri: str, platform: int, timeout: int
) -> Tuple[Optional[str], Optional[str]]:
    params = {"code": code, "redirect_uri": redirect_uri, "platform": platform, "newUser": "undefined"}
    response = session.get(f"{CLOUD_BASE_URL}/oauth", params=params, allow_redirects=True, timeout=timeout)
    response.raise_for_status()
    return session.cookies.get("model_token"), session.cookies.get("model_user_id")


def _warm_home(session: requests.Session, ts: int, timeout: int) -> None:
    session.get(f"{CLOUD_BASE_URL}/es/", params={"ts": ts}, timeout=timeout)


def login(
    account: str,
    password: str,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    redirect_uri: Optional[str] = None,
    platform: int = 2,
    timeout: int = 15,
) -> LoginResult:
    ts = int(time.time() * 1000)
    redirect = redirect_uri or f"{CLOUD_BASE_URL}/es/?ts={ts}"

    session = _build_session()
    session.headers["Referer"] = (
        f"{ID_BASE_URL}/?lang=es-ES&client_id={client_id}&app_id=creality_model"
        f"&redirect_uri={redirect}&platform={platform}"
    )

    token, user_id = _post_credentials(session, account, password, platform, timeout)
    oauth_code = _authorize_code(session, token, user_id, client_id, redirect, platform, timeout)
    model_token, model_user_id = _exchange_code_for_token(session, oauth_code, redirect, platform, timeout)
    _warm_home(session, ts, timeout)

    return LoginResult(
        session=session,
        token=token,
        user_id=str(user_id),
        oauth_code=oauth_code,
        model_token=model_token,
        model_user_id=model_user_id,
    )
