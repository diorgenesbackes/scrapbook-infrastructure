from pathlib import Path
import secrets


root = Path(__file__).resolve().parents[1]
destination = root / ".env"
template = (root / ".env.example").read_text(encoding="utf-8")
lines = template.splitlines()
for index, line in enumerate(lines):
    if line.startswith(("SCRAPBOOK_DB_ADMIN_PASSWORD=", "SCRAPBOOK_DB_APP_PASSWORD=", "SCRAPBOOK_DB_MIGRATOR_PASSWORD=")):
        lines[index] = line + secrets.token_hex(32)

try:
    destination.touch(mode=0o600, exist_ok=False)
except FileExistsError:
    raise SystemExit("Arquivo .env já existe.") from None

destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Configuração local criada em .env.")
