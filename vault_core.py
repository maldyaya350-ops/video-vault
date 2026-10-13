"""Video Vault core: encrypted container format, key handling, attempt guard.

No GUI dependencies, so it can be unit-tested and reused by both apps.

Container layout (all integers big-endian)::

    [ optional player stub (EXE) ]
    HEADER  (4096 bytes, fixed)
        prefix  : magic(8) version(2) log2N(1) r(1) p(1) salt(16) nonce(12)
        blob_len: 2 bytes
        blob    : AES-GCM(KEK, data_key(32) + JSON metadata), AAD = prefix
        padding : random bytes up to 4096
    CHUNKS  : n * AES-GCM(data_key) of up to 1 MiB plaintext each (+16 tag)
    [ trailer (24 bytes): payload_offset(8) payload_len(8) b"VVAULTEN" ]  (EXE mode only)

* The password is never stored. It is stretched with scrypt into a key-encryption
  key (KEK) that unwraps a random per-file data key.
* Because only the small header is password-wrapped, the password can be changed
  later without re-encrypting the video.
* Every chunk is authenticated (index and chunk count are bound in the AAD), so
  tampering, truncation or reordering is detected, and chunks can be decrypted
  independently, which allows seeking without decrypting the whole file.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import shutil
import struct
import threading
import time
import unicodedata
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"VVAULT01"
TRAILER_MAGIC = b"VVAULTEN"
TRAILER_FMT = ">QQ8s"
TRAILER_SIZE = struct.calcsize(TRAILER_FMT)
HEADER_SIZE = 4096
PREFIX_FMT = ">8sHBBB16s12s"
PREFIX_SIZE = struct.calcsize(PREFIX_FMT)
VERSION = 1
CHUNK = 1 << 20
TAG = 16
SCRYPT_LOG2_N = 16  # 64 MiB, ~0.2-0.5 s per guess
SCRYPT_R = 8
SCRYPT_P = 1
MIN_PASSWORD_LEN = 10

ProgressCb = Callable[[float], None]
CancelCb = Callable[[], bool]


class VaultError(Exception):
    pass


class WrongPassword(VaultError):
    pass


class CorruptVault(VaultError):
    pass


class Cancelled(VaultError):
    pass


# --------------------------------------------------------------------------- helpers
def _norm(password: str) -> bytes:
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def _derive(password: str, salt: bytes, log2n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=1 << log2n, r=r, p=p).derive(_norm(password))


def _nonce(index: int) -> bytes:
    return struct.pack(">IQ", 0, index)


def _aad(index: int, total: int) -> bytes:
    return struct.pack(">QQ", index, total)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n} B"


def _pack_header(dek: bytes, meta: dict, password: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    prefix = struct.pack(PREFIX_FMT, MAGIC, VERSION, SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P, salt, nonce)
    kek = _derive(password, salt, SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P)
    blob = AESGCM(kek).encrypt(nonce, dek + json.dumps(meta, ensure_ascii=False).encode("utf-8"), prefix)
    header = prefix + struct.pack(">H", len(blob)) + blob
    if len(header) > HEADER_SIZE:
        raise VaultError("Metadata too large.")
    return header + os.urandom(HEADER_SIZE - len(header))


# --------------------------------------------------------------------------- password policy
_COMMON = {
    "password", "password1", "password123", "123456789", "1234567890", "qwertyuiop",
    "iloveyou", "admin123", "letmein123", "welcome123", "12345678910", "0123456789",
    "abc123456", "qwerty123", "11111111", "1q2w3e4r5t", "passw0rd", "p@ssw0rd",
}


def password_strength(pw: str) -> tuple[int, float]:
    """Return (score 0-4, estimated entropy bits). Deliberately conservative."""
    if not pw:
        return 0, 0.0
    pool = 0
    pool += 26 if any(c.islower() for c in pw) else 0
    pool += 26 if any(c.isupper() for c in pw) else 0
    pool += 10 if any(c.isdigit() for c in pw) else 0
    pool += 33 if any(not c.isalnum() for c in pw) else 0
    if any(ord(c) > 127 and c.isalpha() for c in pw):
        pool += 30
    unique = len(set(pw))
    bits = unique * math.log2(max(pool, 2)) * 0.7 + (len(pw) - unique) * 0.5
    if pw.lower() in _COMMON:
        bits = min(bits, 10)
    score = 0 if bits < 28 else 1 if bits < 40 else 2 if bits < 55 else 3 if bits < 70 else 4
    return score, bits


def validate_password(pw: str) -> Optional[str]:
    """Return None if acceptable, otherwise an error code: short | common | weak."""
    if len(pw) < MIN_PASSWORD_LEN:
        return "short"
    if pw.lower() in _COMMON:
        return "common"
    if password_strength(pw)[0] < 2:
        return "weak"
    return None


def generate_password(length: int = 18) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%^&*-_=+"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw)):
            return pw


# --------------------------------------------------------------------------- locating payloads
def locate_payload(path: str | os.PathLike) -> Optional[tuple[int, int]]:
    """Find a vault inside *path*: appended to an EXE (trailer) or a plain .vvault file."""
    path = Path(path)
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size >= TRAILER_SIZE:
            f.seek(size - TRAILER_SIZE)
            off, length, magic = struct.unpack(TRAILER_FMT, f.read(TRAILER_SIZE))
            if magic == TRAILER_MAGIC and off + length + TRAILER_SIZE == size:
                return off, length
        f.seek(0)
        if f.read(len(MAGIC)) == MAGIC:
            return 0, size
    return None


# --------------------------------------------------------------------------- writer
def create_vault(
    src: str | os.PathLike,
    dst: str | os.PathLike,
    password: str,
    *,
    stub: str | os.PathLike | None = None,
    title: str | None = None,
    progress: ProgressCb | None = None,
    should_cancel: CancelCb | None = None,
) -> dict:
    """Encrypt *src* into *dst* (streaming; memory use is ~one chunk). Returns a summary dict."""
    src, dst = Path(src), Path(dst)
    size = src.stat().st_size
    if size == 0:
        raise VaultError("The source file is empty.")
    nchunks = -(-size // CHUNK)
    dek = secrets.token_bytes(32)
    aes = AESGCM(dek)
    sha = hashlib.sha256()
    tmp = dst.with_name(dst.name + ".part")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            offset = 0
            if stub:
                with open(stub, "rb") as fs:
                    shutil.copyfileobj(fs, fo, 1 << 20)
                offset = fo.tell()
            fo.write(b"\0" * HEADER_SIZE)
            for i in range(nchunks):
                if should_cancel and should_cancel():
                    raise Cancelled()
                buf = fi.read(CHUNK)
                if len(buf) != min(CHUNK, size - i * CHUNK):
                    raise VaultError("The source file changed while it was being read.")
                sha.update(buf)
                fo.write(aes.encrypt(_nonce(i), buf, _aad(i, nchunks)))
                if progress:
                    progress((i + 1) / nchunks)
            payload_len = HEADER_SIZE + size + nchunks * TAG
            meta = {
                "name": src.name[:200], "size": size, "sha256": sha.hexdigest(),
                "chunk": CHUNK, "chunks": nchunks, "title": (title or src.stem)[:100],
                "created": int(time.time()),
            }
            end = fo.tell()
            fo.seek(offset)
            fo.write(_pack_header(dek, meta, password))
            fo.seek(end)
            if stub:
                fo.write(struct.pack(TRAILER_FMT, offset, payload_len, TRAILER_MAGIC))
        os.replace(tmp, dst)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return {"input_size": size, "output_size": dst.stat().st_size, "sha256": meta["sha256"]}


# --------------------------------------------------------------------------- reader
class VaultReader:
    """Random-access decrypting reader. Thread-safe."""

    def __init__(self, path: str | os.PathLike, offset: int | None = None, length: int | None = None):
        self.path = Path(path)
        if offset is None:
            loc = locate_payload(self.path)
            if not loc:
                raise CorruptVault("Not a Video Vault file.")
            offset, length = loc
        self.offset, self.length = offset, length
        self._lock = threading.RLock()
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._f = open(self.path, "rb")
        self._dek: bytes | None = None
        self.meta: dict = {}
        self._f.seek(self.offset)
        raw = self._f.read(HEADER_SIZE)
        if len(raw) < HEADER_SIZE:
            raise CorruptVault("Header is truncated.")
        magic, ver, self._n, self._r, self._p, self._salt, self._nonce = struct.unpack(PREFIX_FMT, raw[:PREFIX_SIZE])
        if magic != MAGIC or ver != VERSION:
            raise CorruptVault("Unsupported file format or version.")
        (blob_len,) = struct.unpack(">H", raw[PREFIX_SIZE:PREFIX_SIZE + 2])
        self._prefix = raw[:PREFIX_SIZE]
        self._blob = raw[PREFIX_SIZE + 2:PREFIX_SIZE + 2 + blob_len]
        self.file_id = hashlib.sha256(self._salt).hexdigest()[:16]

    # -- lifecycle
    def close(self) -> None:
        with self._lock:
            self._f.close()
            self._cache.clear()
            self._dek = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- unlock
    def unlock(self, password: str) -> dict:
        kek = _derive(password, self._salt, self._n, self._r, self._p)
        try:
            plain = AESGCM(kek).decrypt(self._nonce, self._blob, self._prefix)
        except InvalidTag:
            raise WrongPassword() from None
        self._dek = plain[:32]
        self.meta = json.loads(plain[32:].decode("utf-8"))
        self.size = int(self.meta["size"])
        self.chunk = int(self.meta["chunk"])
        self.nchunks = int(self.meta["chunks"])
        expected = HEADER_SIZE + self.size + self.nchunks * TAG
        if self.length is not None and self.length != expected:
            raise CorruptVault("File length does not match its header (truncated or modified).")
        return self.meta

    # -- data access
    def _chunk(self, i: int) -> bytes:
        with self._lock:
            hit = self._cache.get(i)
            if hit is not None:
                self._cache.move_to_end(i)
                return hit
            plain_len = min(self.chunk, self.size - i * self.chunk)
            self._f.seek(self.offset + HEADER_SIZE + i * (self.chunk + TAG))
            ct = self._f.read(plain_len + TAG)
            try:
                data = AESGCM(self._dek).decrypt(_nonce(i), ct, _aad(i, self.nchunks))
            except InvalidTag:
                raise CorruptVault(f"Data block {i} failed authentication (file damaged or tampered).") from None
            self._cache[i] = data
            while len(self._cache) > 6:
                self._cache.popitem(last=False)
            return data

    def read(self, pos: int, n: int) -> bytes:
        if self._dek is None:
            raise VaultError("Vault is locked.")
        if pos < 0 or pos >= self.size or n <= 0:
            return b""
        n = min(n, self.size - pos)
        out = bytearray()
        while n > 0:
            i, off = divmod(pos, self.chunk)
            piece = self._chunk(i)[off:off + n]
            out += piece
            pos += len(piece)
            n -= len(piece)
        return bytes(out)

    def verify(self, progress: ProgressCb | None = None, should_cancel: CancelCb | None = None) -> bool:
        """Authenticate every chunk and compare the SHA-256 of the whole video."""
        sha = hashlib.sha256()
        for i in range(self.nchunks):
            if should_cancel and should_cancel():
                raise Cancelled()
            with self._lock:
                self._cache.pop(i, None)
            sha.update(self._chunk(i))
            if progress:
                progress((i + 1) / self.nchunks)
        with self._lock:
            self._cache.clear()
        return sha.hexdigest() == self.meta["sha256"]

    def export_to(self, dst: str | os.PathLike, progress: ProgressCb | None = None) -> None:
        with open(dst, "wb") as f:
            for i in range(self.nchunks):
                f.write(self._chunk(i))
                if progress:
                    progress((i + 1) / self.nchunks)


# --------------------------------------------------------------------------- change password
def change_password(path: str | os.PathLike, old: str, new: str) -> None:
    """Re-wrap the data key under a new password. Only the 4 KiB header is rewritten."""
    loc = locate_payload(path)
    if not loc:
        raise CorruptVault("Not a Video Vault file.")
    offset, length = loc
    with VaultReader(path, offset, length) as r:
        r.unlock(old)
        dek, meta = r._dek, r.meta
    header = _pack_header(dek, meta, new)
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(header)
        f.flush()
        os.fsync(f.fileno())


# --------------------------------------------------------------------------- attempt limiter
class AttemptGuard:
    """Persistent failed-attempt counter with growing lockouts (client-side convenience limit).

    NOTE: this slows down someone using the supplied player. It cannot stop an attacker who
    copies the file and guesses offline; that is what scrypt and a strong password are for.
    """

    MAX_BEFORE_LOCK = 5

    def __init__(self, store_dir: str | os.PathLike, file_id: str):
        self.path = Path(store_dir) / "attempts.json"
        self.file_id = file_id

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text("utf-8")).get(self.file_id, {})
        except (OSError, ValueError):
            return {}

    def _save(self, entry: dict) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        if entry:
            data[self.file_id] = entry
        else:
            data.pop(self.file_id, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), "utf-8")

    def lock_remaining(self) -> int:
        e = self._load()
        return max(0, int(e.get("until", 0) - time.time()))

    def failures(self) -> int:
        return int(self._load().get("fails", 0))

    def record_failure(self) -> int:
        e = self._load()
        fails = int(e.get("fails", 0)) + 1
        entry = {"fails": fails, "until": e.get("until", 0)}
        if fails % self.MAX_BEFORE_LOCK == 0:
            step = fails // self.MAX_BEFORE_LOCK
            entry["until"] = time.time() + min(3600, 30 * 2 ** (step - 1))
        self._save(entry)
        return fails

    def reset(self) -> None:
        self._save({})
