import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
PASSWORD_NAMES = ("SCRAPBOOK_DB_APP_PASSWORD", "SCRAPBOOK_DB_MIGRATOR_PASSWORD")
ROLE_PASSWORDS = """
\\getenv app_password SCRAPBOOK_DB_APP_PASSWORD
\\getenv migrator_password SCRAPBOOK_DB_MIGRATOR_PASSWORD
SELECT format('ALTER ROLE %I PASSWORD %L', role.rolname, credentials.password)
FROM pg_catalog.pg_authid AS role
JOIN (VALUES ('scrapbook_app', :'app_password'), ('scrapbook_migrator', :'migrator_password'))
    AS credentials(name, password) ON credentials.name = role.rolname
WHERE role.rolpassword IS NULL \\gexec
"""


def run(stage, args, *, env=None, stdin=None, cwd=ROOT):
    try:
        return subprocess.run(
            args, cwd=cwd, env=env, input=stdin, text=True, capture_output=True, check=True,
        ).stdout.strip()
    except OSError:
        raise ValueError(f"{stage}: executável ou caminho indisponível.") from None
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{stage}: comando recusado (código {error.returncode}).") from None


def prepare(compose, liquibase):
    launcher = liquibase / "scripts/migrate.py"
    bootstrap_file = liquibase / "config/bootstrap.sql"
    if not launcher.is_file() or not bootstrap_file.is_file():
        raise ValueError("Arquivos do Liquibase: scripts/migrate.py e config/bootstrap.sql são obrigatórios.")
    run("Ferramenta Liquibase", ["liquibase", "--version"])

    settings = dict(
        line.split("=", 1)
        for line in run("Configuração do Compose", [*compose, "config", "--environment"]).splitlines() if "=" in line
    )
    passwords = {name: settings.get(name, "") for name in PASSWORD_NAMES}
    if any(not re.fullmatch(r"[a-fA-F0-9]{32,128}", value) for value in passwords.values()):
        raise ValueError("Use senhas locais hexadecimais de 32 a 128 caracteres para aplicação e migração.")

    binding = run("Porta do PostgreSQL", [*compose, "port", "postgres", "5432"])
    match = re.fullmatch(r"127\.0\.0\.1:(\d+)", binding)
    if not match:
        raise ValueError("A porta do PostgreSQL deve estar publicada exclusivamente em loopback.")

    try:
        bootstrap = bootstrap_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ValueError("Bootstrap PostgreSQL: leitura de config/bootstrap.sql indisponível.") from None
    run(
        "Bootstrap PostgreSQL",
        [
            *compose, "exec", "-T",
            "-e", PASSWORD_NAMES[0], "-e", PASSWORD_NAMES[1],
            "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "scrapbook",
            "--single-transaction", "-f", "-",
        ],
        env=os.environ | passwords,
        stdin=bootstrap + "\n" + ROLE_PASSWORDS,
    )
    for role, password_name in zip(("scrapbook_app", "scrapbook_migrator"), PASSWORD_NAMES):
        run(
            f"Credencial existente de {role}",
            [*compose, "exec", "-T", "-e", "PGPASSWORD", "postgres", "psql", "-Xw", "-h", "postgres",
             "-U", role, "-d", "scrapbook", "-c", "SELECT 1"],
            env=os.environ | {"PGPASSWORD": passwords[password_name]},
        )

    run(
        "Migração Liquibase",
        [sys.executable, str(launcher), "update"],
        env=os.environ | {
            "LIQUIBASE_COMMAND_URL": f"jdbc:postgresql://127.0.0.1:{match.group(1)}/scrapbook",
            "LIQUIBASE_COMMAND_PASSWORD": passwords[PASSWORD_NAMES[1]],
        },
        cwd=liquibase,
    )


def main():
    parser = argparse.ArgumentParser(description="Prepara o banco descartável ou persistente do Compose local.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--project-name")
    parser.add_argument("--liquibase-dir", type=Path, default=ROOT.parent / "scrapbook-liquibase")
    args = parser.parse_args()
    compose = ["docker", "compose", "--file", str(ROOT / "compose.yaml"), "--env-file", str(args.env_file.resolve())]
    if args.project_name:
        compose.extend(("--project-name", args.project_name))

    execution = uuid4()
    try:
        prepare(compose, args.liquibase_dir.resolve())
    except ValueError as error:
        print(f"Falha ao aplicar a alteração de banco. execução={execution} ambiente=local", file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 1

    print(f"Base PostgreSQL preparada pelo Liquibase. execução={execution} ambiente=local")
    return 0


if __name__ == "__main__":
    sys.exit(main())
