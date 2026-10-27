"""Testes das funções de chaves de service account (sk.identity.keys)."""

from pathlib import Path

import pytest

from sk.identity.keys import (
    DEFAULT_EXPIRES_IN_DAYS,
    KeyFileError,
    generate_key_pair,
    parse_public_key_file,
    read_key_file,
    sign_jwt_assertion,
    update_key_file,
    write_key_file,
)


def test_generate_key_pair_creates_valid_rsa_key_and_fingerprint() -> None:
    keypair = generate_key_pair(expires_in_days=30)
    assert keypair.private_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert keypair.public_pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert len(keypair.fingerprint) == 64  # SHA-256 hex
    assert "T" in keypair.expires_at


def test_generate_key_pair_rejects_invalid_expiry() -> None:
    with pytest.raises(ValueError, match="expires-in must be greater than 0"):
        generate_key_pair(expires_in_days=0)
    with pytest.raises(ValueError, match="cannot exceed 365 days"):
        generate_key_pair(expires_in_days=400)


def test_write_and_read_key_file(tmp_path: Path) -> None:
    keypair = generate_key_pair()
    target = tmp_path / "sa.json"
    write_key_file(target, private_pem=keypair.private_pem, user_id="u-123", key_id="k-456")

    # Recusa sobrescrita
    with pytest.raises(KeyFileError, match="already exists"):
        write_key_file(target, private_pem=keypair.private_pem)

    data = read_key_file(target)
    assert data["type"] == "serviceaccount"
    assert data["key"] == keypair.private_pem
    assert data["userId"] == "u-123"
    assert data["keyId"] == "k-456"


def test_update_key_file(tmp_path: Path) -> None:
    keypair = generate_key_pair()
    target = tmp_path / "sa-pending.json"
    write_key_file(target, private_pem=keypair.private_pem)

    # Inicialmente sem keyId
    with pytest.raises(KeyFileError, match="missing or empty 'userId' field"):
        read_key_file(target)

    update_key_file(target, user_id="u-final", key_id="k-final")
    data = read_key_file(target)
    assert data["userId"] == "u-final"
    assert data["keyId"] == "k-final"
    assert data["key"] == keypair.private_pem


def test_parse_public_key_file_valid_and_invalid(tmp_path: Path) -> None:
    keypair = generate_key_pair()
    pub_file = tmp_path / "valid.pub"
    pub_file.write_text(keypair.public_pem, encoding="utf-8")

    pem, fp, expires_at = parse_public_key_file(pub_file, expires_in_days=DEFAULT_EXPIRES_IN_DAYS)
    assert pem == keypair.public_pem
    assert fp == keypair.fingerprint
    assert "T" in expires_at

    # Arquivo corrompido
    bad_file = tmp_path / "bad.pub"
    bad_file.write_text("not a pem", encoding="utf-8")
    with pytest.raises(KeyFileError, match="not a valid PEM public key"):
        parse_public_key_file(bad_file)


def test_sign_jwt_assertion() -> None:
    keypair = generate_key_pair()
    assertion = sign_jwt_assertion(
        keypair.private_pem,
        key_id="k-1",
        user_id="u-1",
        issuer="https://auth.example.com",
    )
    parts = assertion.split(".")
    assert len(parts) == 3


def _stdin(monkeypatch: pytest.MonkeyPatch, content: bytes, *, tty: bool = False) -> None:
    import io

    class FakeStdin:
        buffer = io.BytesIO(content)

        def isatty(self) -> bool:
            return tty

    monkeypatch.setattr("sys.stdin", FakeStdin())


def test_parse_public_key_reads_the_standard_input_when_the_path_is_a_dash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keypair = generate_key_pair()
    _stdin(monkeypatch, keypair.public_pem.encode())
    pem, fingerprint, _ = parse_public_key_file(Path("-"))
    assert pem == keypair.public_pem
    assert fingerprint == keypair.fingerprint


def test_parse_public_key_from_a_terminal_fails_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _stdin(monkeypatch, b"", tty=True)
    with pytest.raises(KeyFileError, match="is a terminal"):
        parse_public_key_file(Path("-"))


def test_parse_public_key_from_an_empty_stdin_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _stdin(monkeypatch, b"  \n")
    with pytest.raises(KeyFileError, match="is empty"):
        parse_public_key_file(Path("-"))


def test_parse_public_key_from_a_huge_stdin_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    _stdin(monkeypatch, b"A" * (64 * 1024 + 1))
    with pytest.raises(KeyFileError, match="larger than 64 KiB"):
        parse_public_key_file(Path("-"))


def test_parse_public_key_from_a_bad_stdin_never_echoes_the_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stdin(monkeypatch, b"conteudo-secreto-qualquer")
    with pytest.raises(KeyFileError) as caught:
        parse_public_key_file(Path("-"))
    assert "standard input is not a valid PEM public key" in str(caught.value)
    assert "conteudo-secreto" not in str(caught.value)


def test_a_file_named_dash_is_reachable_with_a_relative_path(tmp_path: Path) -> None:
    keypair = generate_key_pair()
    (tmp_path / "-").write_text(keypair.public_pem, encoding="utf-8")
    pem, _, _ = parse_public_key_file(tmp_path / "-")
    assert pem == keypair.public_pem
