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

    def test_password_capture_redacts_captured_span(self):
        r = Redactor()
        text = "password = password"
        result = r.redact(text)
        assert result == "password = [REDACTED:password]"


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


class TestNewSecretPatterns:
    """Tests for the new secret patterns added to the Redactor."""

    def test_github_server_to_server_token(self):
        r = Redactor()
        text = "GH_TOKEN=ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = r.redact(text)
        assert "ghs_" not in result
        assert "[REDACTED:api_key]" in result

    def test_github_refresh_token(self):
        r = Redactor()
        text = "REFRESH_TOKEN=ghr_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = r.redact(text)
        assert "ghr_" not in result
        assert "[REDACTED:api_key]" in result

    def test_slack_webhook_url(self):
        r = Redactor()
        # Build URL dynamically to avoid GitHub push protection false positives
        base = "https://hooks.slack.com"
        path = "/services/TFAKEFAKE/BFAKEFAKE/fakefakefakefakefakefake"
        text = f"WEBHOOK={base}{path}"
        result = r.redact(text)
        assert "hooks.slack.com" not in result
        assert "[REDACTED:webhook]" in result

    def test_npm_token(self):
        r = Redactor()
        text = "NPM_TOKEN=npm_abcdefghijklmnopqrstuvwxyz0123456789"
        result = r.redact(text)
        assert "npm_" not in result
        assert "[REDACTED:api_key]" in result

    def test_pypi_token(self):
        r = Redactor()
        # PyPI tokens are at least 100 chars after the prefix
        token = "pypi-" + "a" * 120
        text = f"PYPI_TOKEN={token}"
        result = r.redact(text)
        assert "pypi-" not in result
        assert "[REDACTED:api_key]" in result

    def test_google_api_key(self):
        r = Redactor()
        text = "GOOGLE_KEY=AIzaSyA1234567890abcdefghijklmnopqrstuvw"
        result = r.redact(text)
        assert "AIza" not in result
        assert "[REDACTED:api_key]" in result

    def test_stripe_secret_key(self):
        r = Redactor()
        text = "STRIPE_KEY=sk_test_abcdefghijklmnopqrstuvwxyz"
        result = r.redact(text)
        assert "sk_test_" not in result
        assert "[REDACTED:api_key]" in result

    def test_stripe_publishable_key(self):
        r = Redactor()
        text = "STRIPE_PK=pk_live_abcdefghijklmnopqrstuvwxyz"
        result = r.redact(text)
        assert "pk_live_" not in result
        assert "[REDACTED:api_key]" in result

    def test_twilio_key(self):
        r = Redactor()
        # Use repeated hex to avoid GitHub push protection false positives
        text = "TWILIO_KEY=SKaaaa0000bbbb1111cccc2222dddd3333"
        result = r.redact(text)
        assert "SKaaaa" not in result
        assert "[REDACTED:api_key]" in result

    def test_sendgrid_key(self):
        r = Redactor()
        text = "SENDGRID_KEY=SG.abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvwxyz"
        result = r.redact(text)
        assert "SG." not in result
        assert "[REDACTED:api_key]" in result

    def test_azure_storage_account_key(self):
        r = Redactor()
        key = "AccountKey=" + "a" * 88
        text = f"AZURE_CONN={key}"
        result = r.redact(text)
        assert "a" * 88 not in result
        assert "[REDACTED:api_key]" in result


class TestPlaceholder:
    def test_custom_placeholder(self):
        r = Redactor(placeholder="***")
        text = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = r.redact(text)
        assert "***" in result
        assert "ghp_" not in result
