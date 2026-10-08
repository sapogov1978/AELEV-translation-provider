// Historical standalone provisioning; infrastructure Compose now owns startup.
import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { closeSync, existsSync, fsyncSync, openSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const envPath = fileURLToPath(new URL("../../translator-service/.env", import.meta.url));

export function configuration(existing, password) {
  if (existing) {
    const line = existing.split("\n").find(value => value.startsWith("AELEV_TRANSLATOR_DATABASE_URL="));
    if (!line) throw new Error("Missing owned database setting");
    const parsed = new URL(line.slice(line.indexOf("=") + 1).replace("postgresql+psycopg:", "postgresql:"));
    if (parsed.username !== "translator_service" || parsed.hostname !== "translator-postgres" || parsed.pathname !== "/translator_service") {
      throw new Error("Unexpected database owner or endpoint");
    }
    return { password: decodeURIComponent(parsed.password), contents: existing };
  }
  return { password, contents: [
    "# Generated local secret configuration; never commit or print it.",
    "AELEV_ENVIRONMENT=local",
    "AELEV_TRANSLATOR_IMAGE=aelev/translator-service:kafka-v1",
    `AELEV_TRANSLATOR_DATABASE_URL=postgresql+psycopg://translator_service:${password}@translator-postgres:5432/translator_service`,
    "AELEV_TRANSLATOR_MODEL_MEMORY=4g", "AELEV_TRANSLATOR_MODEL_CPUS=2", "",
  ].join("\n") };
}

function main() {
  const existing = existsSync(envPath) ? readFileSync(envPath, "utf8") : "";
  const config = configuration(existing, randomBytes(32).toString("base64url"));
  if (!config.password || /[\r\n]/.test(config.password)) throw new Error("Invalid local credential");
  // Password goes through stdin, not argv, tool output or a checked-in file.
  const escaped = config.password.replaceAll("'", "''");
  const sql = `
SELECT 'CREATE ROLE translator_service LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='translator_service') \\gexec
ALTER ROLE translator_service LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '${escaped}';
SELECT 'CREATE DATABASE translator_service OWNER translator_service'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='translator_service') \\gexec
REVOKE CONNECT ON DATABASE translator_service FROM PUBLIC;
GRANT CONNECT ON DATABASE translator_service TO translator_service;
`;
  const temporary = envPath + ".provisioning";
  // Persist the generated secret before granting the role; a retry reuses it.
  if (!existing) {
    const fd = openSync(temporary, "wx", 0o600);
    try { writeFileSync(fd, config.contents); fsyncSync(fd); } finally { closeSync(fd); }
    renameSync(temporary, envPath);
  }
  execFileSync("docker", ["exec", "-i", "aelev-infrastructure-postgres-1", "sh", "-c",
    'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1'], {
    cwd: root, input: sql, encoding: "utf8", timeout: 30000, stdio: ["pipe", "pipe", "pipe"],
  });
  console.log(JSON.stringify({ event: "translator_database_provisioned", database: "translator_service" }));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try { main(); }
  catch { console.error(JSON.stringify({ event: "translator_database_provisioning_failed" })); process.exitCode = 1; }
}
