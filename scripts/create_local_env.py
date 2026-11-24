import argparse
from pathlib import Path
import secrets


def invitation_settings():
    return {
        "SCRAPBOOK_INVITATION_HASH_KEY_ID": "local-hash-v1",
        "SCRAPBOOK_INVITATION_HASH_KEY": secrets.token_hex(32),
        "SCRAPBOOK_INVITATION_ENCRYPTION_KEY_ID": "local-encryption-v1",
        "SCRAPBOOK_INVITATION_ENCRYPTION_KEY": secrets.token_hex(32),
    }


def enable_invitations(path):
    if path.stat().st_mode & 0o077:
        raise SystemExit("Restrinja as permissões do .env ao proprietário.")

    original = path.read_text(encoding="utf-8")
    settings = invitation_settings()
    names = {line.partition("=")[0].strip().removeprefix("export ") for line in original.splitlines()}
    if names.intersection(settings):
        raise SystemExit("Arquivo .env já contém configuração de convites. Preserve as chaves existentes.")

    with path.open("a", encoding="utf-8") as file:
        if original and not original.endswith("\n"):
            file.write("\n")
        for name, value in settings.items():
            file.write(f"{name}={value}\n")
    print("Chaves de convite criadas no .env.")


root = Path(__file__).resolve().parents[1]
destination = root / ".env"
parser = argparse.ArgumentParser()
parser.add_argument("--enable-invitations", action="store_true")
args = parser.parse_args()
if args.enable_invitations and destination.exists():
    enable_invitations(destination)
    raise SystemExit(0)

template = (root / ".env.example").read_text(encoding="utf-8")
settings = invitation_settings()
lines = template.splitlines()
for index, line in enumerate(lines):
    name, _, _ = line.partition("=")
    if name in settings:
        lines[index] = name + "=" + settings[name]
    elif name in {"SCRAPBOOK_DB_ADMIN_PASSWORD", "SCRAPBOOK_DB_APP_PASSWORD", "SCRAPBOOK_DB_MIGRATOR_PASSWORD"}:
        lines[index] = line + secrets.token_hex(32)

try:
    destination.touch(mode=0o600, exist_ok=False)
except FileExistsError:
    raise SystemExit("Arquivo .env já existe.") from None

destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Configuração local criada em .env.")
