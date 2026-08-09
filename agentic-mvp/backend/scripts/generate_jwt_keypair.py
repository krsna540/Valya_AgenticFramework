#!/usr/bin/env python3
"""Generate an RS256 keypair for JWT signing and print .env-ready lines.

    python scripts/generate_jwt_keypair.py >> ../.env

Usage note: this APPENDS to whatever file you redirect into, so run it once
against a fresh .env (copied from .env.example) rather than repeatedly —
running it twice just gives you two JWT_PRIVATE_KEY lines and Pydantic's
BaseSettings will use whichever env parser sees last, which is a confusing
way to rotate a key. To rotate deliberately: generate a new pair, replace
both JWT_PRIVATE_KEY/JWT_PUBLIC_KEY lines in .env, restart every service
(app.stream and the agent workers need the new JWT_PUBLIC_KEY to verify
tokens the API service mints after the restart).

Keys never get written anywhere but stdout — nothing in this repo commits a
real key pair. .env is gitignored (see backend/.dockerignore's sibling
.gitignore at the repo root); do not add these values to docker-compose.yml
directly.
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    # .env values with embedded newlines need to be single-line for most
    # loaders (including pydantic-settings' default .env parser) — \n
    # escapes round-trip correctly because PyJWT/python-jose both accept a
    # PEM string with literal "\n" sequences already unescaped by the
    # shell/dotenv loader before it reaches jwt.decode/encode.
    print(f"JWT_PRIVATE_KEY=\"{private_pem.replace(chr(10), chr(92) + 'n')}\"")
    print(f"JWT_PUBLIC_KEY=\"{public_pem.replace(chr(10), chr(92) + 'n')}\"")


if __name__ == "__main__":
    main()
