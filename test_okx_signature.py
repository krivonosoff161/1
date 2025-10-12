import base64
import hashlib
import hmac
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # загружаем .env


def get_env_vars():
    api_key = os.getenv("OKX_API_KEY")
    api_secret = os.getenv("OKX_API_SECRET")
    passphrase = os.getenv("OKX_PASSPHRASE")
    return api_key, api_secret, passphrase


def generate_okx_signature(secret, timestamp, method, request_path, body=""):
    message = timestamp + method + request_path + body
    hmac_key = base64.b64decode(secret)
    signature = base64.b64encode(
        hmac.new(hmac_key, message.encode("utf-8"), hashlib.sha256).digest()
    )
    return signature.decode()


def main():
    api_key, api_secret, passphrase = get_env_vars()
    print(f"API Key: {api_key}")
    print(f"API Secret: {api_secret}")
    print(f"Passphrase: {passphrase}")

    if not all([api_key, api_secret, passphrase]):
        print("Error: One or more environment variables are missing!")
        return

    timestamp = datetime.utcnow().isoformat() + "Z"
    method = "GET"
    request_path = "/api/v5/account/balance"
    body = ""

    try:
        signature = generate_okx_signature(
            api_secret, timestamp, method.lower(), request_path, body
        )
        print(f"Signature: {signature}")
    except Exception as e:
        print(f"Error generating signature: {e}")


if __name__ == "__main__":
    main()
