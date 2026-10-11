#!/usr/bin/env node
// Local development runner. Loads the root .env, starts Postgres and Redis in
// Docker, applies migrations, then runs the API, worker, and web app in one
// terminal with labelled output. Ctrl+C stops everything.
//
//   node scripts/dev.mjs          # everything
//   node scripts/dev.mjs api      # Docker services, migrations, API, worker
//   node scripts/dev.mjs web      # web app only
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const apiDir = path.join(root, "apps/api");
const webDir = path.join(root, "apps/web");
const target = process.argv[2] ?? "all";
if (!["all", "api", "web"].includes(target)) {
  console.error(`Unknown target "${target}". Use: all, api, or web.`);
  process.exit(1);
}

const envFile = path.join(root, ".env");
if (!existsSync(envFile)) {
  console.error("Missing .env. Copy .env.example to .env and fill in the secrets first.");
  process.exit(1);
}
const env = { ...process.env };
for (const [key, value] of Object.entries(parseEnv(readFileSync(envFile, "utf8")))) {
  if (env[key] === undefined) env[key] = value;
}
const apiPort = env.API_HOST_PORT || "8000";
const webPort = env.WEB_HOST_PORT || "3000";

const COLORS = { api: 36, worker: 35, web: 33, setup: 90 };
function label(name) {
  return `\x1b[${COLORS[name] ?? 37}m${name.padEnd(6)}\x1b[0m│ `;
}
function pipe(stream, name, out) {
  let buffer = "";
  stream.on("data", (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) out.write(label(name) + line + "\n");
  });
  stream.on("end", () => buffer && out.write(label(name) + buffer + "\n"));
}

function runSync(name, cmd, args, cwd) {
  console.log(label(name) + [cmd, ...args].join(" "));
  const res = spawnSync(cmd, args, { cwd, env, stdio: "inherit" });
  if (res.error) {
    console.error(label(name) + `Could not run ${cmd}: ${res.error.message}`);
    process.exit(1);
  }
  if (res.status !== 0) {
    console.error(label(name) + `${cmd} exited with code ${res.status}`);
    process.exit(res.status ?? 1);
  }
}

const children = [];
let stopping = false;
function stopAll(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode === null) {
      try {
        process.kill(-child.pid, "SIGTERM");
      } catch {
        child.kill("SIGTERM");
      }
    }
  }
  setTimeout(() => process.exit(code), 1500).unref();
}
process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));

function start(name, cmd, args, cwd) {
  const child = spawn(cmd, args, { cwd, env, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  pipe(child.stdout, name, process.stdout);
  pipe(child.stderr, name, process.stderr);
  child.on("error", (err) => {
    console.error(label(name) + `Could not start ${cmd}: ${err.message}`);
    stopAll(1);
  });
  child.on("exit", (code, signal) => {
    if (stopping) return;
    console.error(label(name) + `exited (${signal ?? code}). Stopping everything.`);
    stopAll(code || 1);
  });
  children.push(child);
}

if (target !== "web") {
  runSync("setup", "docker", ["compose", "up", "-d", "--wait", "postgres", "redis"], root);
  runSync("setup", "uv", ["run", "alembic", "upgrade", "head"], apiDir);
  start("api", "uv", ["run", "uvicorn", "app.main:app", "--port", apiPort, "--reload"], apiDir);
  start("worker", "uv", ["run", "arq", "app.workers.main.WorkerSettings"], apiDir);
}
if (target !== "api") {
  if (!existsSync(path.join(webDir, "node_modules"))) runSync("setup", "pnpm", ["install"], webDir);
  start("web", "node", ["scripts/with-root-env.mjs", "dev"], webDir);
}

console.log(
  label("setup") +
    [target !== "api" && `web http://localhost:${webPort}`, target !== "web" && `api http://localhost:${apiPort}`]
      .filter(Boolean)
      .join("   ") +
    "   (Ctrl+C stops everything)",
);
