#!/usr/bin/env node
// Runs the Next.js CLI with the repository-root .env loaded, so the web app and
// the API share one configuration file. Variables already present in the
// environment win over the file. WEB_HOST_PORT selects the dev/start port.
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const envFile = path.resolve(appDir, "../../.env");

if (existsSync(envFile)) {
  for (const [key, value] of Object.entries(parseEnv(readFileSync(envFile, "utf8")))) {
    if (process.env[key] === undefined) process.env[key] = value;
  }
}
if (!process.env.PORT && process.env.WEB_HOST_PORT) process.env.PORT = process.env.WEB_HOST_PORT;

const nextBin = path.join(appDir, "node_modules/next/dist/bin/next");
const child = spawn(process.execPath, [nextBin, ...process.argv.slice(2)], {
  cwd: appDir,
  stdio: "inherit",
  env: process.env,
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
