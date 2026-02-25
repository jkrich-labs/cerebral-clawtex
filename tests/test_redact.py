# tests/test_redact.py
from cerebral_clawtex.redact import Redactor


class TestAPIKeyRedaction:
    def test_openai_key(self):
        r = Redactor()
        text = 'OPENAI_API_KEY="sk-proj-abc123def456ghi789jkl012mno"'
        result = r.redact(text)
        assert "sk-proj-" not in result
        assert "[REDACTED:api_key]" in result

    def test_aws_key(self):
        r = Redactor()
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"
        result = r.redact(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED:api_key]" in result

    def test_github_token(self):
        r = Redactor()
        text = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = r.redact(text)
        assert "ghp_" not in result
        assert "[REDACTED:api_key]" in result

    def test_anthropic_key(self):
        r = Redactor()
        text = 'api_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"'
        result = r.redact(text)
        assert "sk-ant-" not in result
        assert "[REDACTED:api_key]" in result


class TestTokenRedaction:
    def test_bearer_token(self):
        r = Redactor()
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
        result = r.redact(text)
        assert "eyJhbG" not in result
        assert "[REDACTED:token]" in result


class TestConnectionStringRedaction:
    def test_postgres_url(self):
        r = Redactor()
        text = 'DATABASE_URL="postgres://admin:secretpass@db.example.com:5432/mydb"'
        result = r.redact(text)
        assert "secretpass" not in result
        assert "[REDACTED:connection_string]" in result

    def test_redis_url(self):
        r = Redactor()
        text = "REDIS_URL=redis://default:mypassword@redis.host:6379/0"
        result = r.redact(text)
        assert "mypassword" not in result
        assert "[REDACTED:connection_string]" in result


class TestPrivateKeyRedaction:
    def test_rsa_private_key(self):
        r = Redactor()
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        result = r.redact(text)
        assert "MIIEpAIBAAKCAQEA" not in result
        assert "[REDACTED:private_key]" in result


class TestGenericSecretRedaction:
    def test_secret_key_assignment(self):
        r = Redactor()
        text = 'DJANGO_SECRET_KEY="super-secret-value-12345678"'
        result = r.redact(text)
        assert "super-secret-value" not in result
        assert "[REDACTED:generic_secret]" in result

    def test_password_assignment(self):
        r = Redactor()
        text = 'password = "MyP@ssw0rd123!"'
        result = r.redact(text)
        assert "MyP@ssw0rd" not in result
        assert "[REDACTED:password]" in result


class TestFalsePositives:
    def test_normal_code_not_redacted(self):
        r = Redactor()
        text = "def calculate_token_count(text: str) -> int:"
        result = r.redact(text)
        assert result == text

    def test_short_values_not_redacted(self):
        r = Redactor()
        text = 'secret = "short"'
        result = r.redact(text)
        # "short" is only 5 chars, below the 8-char threshold
        assert result == text

    def test_import_statements_not_redacted(self):
        r = Redactor()
        text = "from secret_module import secret_function"
        result = r.redact(text)
        assert result == text


class TestCustomPatterns:
    def test_extra_pattern(self):
        r = Redactor(extra_patterns=["CORP_TOKEN_[A-Za-z0-9]+"])
        text = "Using CORP_TOKEN_abc123xyz for auth"
        result = r.redact(text)
        assert "CORP_TOKEN_abc123xyz" not in result
        assert "[REDACTED:custom]" in result


class TestPlaceholder:
    def test_custom_placeholder(self):
        r = Redactor(placeholder="***")
        text = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = r.redact(text)
        assert "***" in result
        assert "ghp_" not in result
