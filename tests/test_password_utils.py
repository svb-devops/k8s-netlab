"""
password_utils 纯逻辑单元测试 — 专为突变测试设计。

覆盖 hash_password / verify_password / needs_upgrade 的所有分支，
确保以下突变能被 kill：
  PW-1: needs_upgrade 返回值取反
  PW-2: verify_password bcrypt 分支始终返回 False
  PW-3: verify_password SHA-256 比较取反
  PW-4: verify_password 异常时返回 True
"""

import hashlib

import pytest

from backend.password_utils import hash_password, verify_password, needs_upgrade


class TestHashPassword:
    def test_returns_bcrypt_prefix(self):
        h = hash_password("mypassword")
        assert h.startswith("$2b$"), "hash_password 必须生成 bcrypt 格式"

    def test_different_salts_each_call(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2, "每次调用应生成不同的盐（bcrypt 内置）"


class TestNeedsUpgrade:
    """PW-1 专项：needs_upgrade 对 bcrypt 返回 False，对 SHA-256 返回 True。"""

    def test_bcrypt_does_not_need_upgrade(self):
        h = hash_password("secret")
        assert needs_upgrade(h) is False, "bcrypt hash 不需要升级"

    def test_bcrypt_2a_prefix_does_not_need_upgrade(self):
        # $2a$ 也是合法的 bcrypt 前缀
        assert needs_upgrade("$2a$12$abcdefghijklmno") is False

    def test_bcrypt_2y_prefix_does_not_need_upgrade(self):
        assert needs_upgrade("$2y$12$abcdefghijklmno") is False

    def test_sha256_needs_upgrade(self):
        sha = hashlib.sha256("secret".encode()).hexdigest()
        assert needs_upgrade(sha) is True, "SHA-256 hash 需要升级"

    def test_plain_text_needs_upgrade(self):
        assert needs_upgrade("plaintext") is True


class TestVerifyPasswordBcrypt:
    """PW-2 专项：bcrypt 正确密码必须返回 True。"""

    def test_correct_password_returns_true(self):
        h = hash_password("correcthorse")
        assert verify_password("correcthorse", h) is True

    def test_wrong_password_returns_false(self):
        h = hash_password("correcthorse")
        assert verify_password("wrongpass", h) is False

    def test_empty_password_wrong_returns_false(self):
        h = hash_password("secret")
        assert verify_password("", h) is False


class TestVerifyPasswordSha256:
    """PW-3 专项：SHA-256 正确密码返回 True，错误密码返回 False。"""

    def _sha256(self, pw: str) -> str:
        return hashlib.sha256(pw.encode()).hexdigest()

    def test_correct_sha256_returns_true(self):
        h = self._sha256("legacy_password")
        assert verify_password("legacy_password", h) is True

    def test_wrong_sha256_returns_false(self):
        h = self._sha256("legacy_password")
        assert verify_password("different_password", h) is False

    def test_sha256_empty_correct_returns_true(self):
        h = self._sha256("")
        assert verify_password("", h) is True

    def test_sha256_empty_wrong_returns_false(self):
        h = self._sha256("something")
        assert verify_password("", h) is False


class TestVerifyPasswordException:
    """PW-4 专项：无效 hash 导致异常时必须返回 False，不得放行。"""

    def test_invalid_hash_returns_false(self):
        # 伪造一个 $2b$ 前缀但内容无效的 hash → bcrypt.checkpw 会抛异常
        assert verify_password("password", "$2b$invalid_hash") is False

    def test_none_hash_returns_false(self):
        # None 不是字符串，startswith 会抛 AttributeError
        assert verify_password("password", None) is False  # type: ignore

    def test_completely_invalid_hash_returns_false(self):
        assert verify_password("password", "not_a_hash_at_all") is False
