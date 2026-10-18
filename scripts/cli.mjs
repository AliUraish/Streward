import { spawn } from 'node:child_process';
import { access, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const tools = {
  insforge: { directory: 'tooling/node_modules/@insforge/cli', bin: 'insforge' },
  manufact: { directory: 'tooling/node_modules/@mcp-use/cli', bin: 'mcp-use' },
  eve: { directory: 'agent-runtime/node_modules/eve', bin: 'eve' },
};
const [name, ...providedArgs] = process.argv.slice(2);
if (!Object.hasOwn(tools, name ?? '')) {
  process.stderr.write('Usage: node scripts/cli.mjs <insforge|manufact|eve> [arguments]\n');
  process.exit(2);
}

const tool = tools[name];
const directory = path.join(root, tool.directory);
let metadata;
try {
  metadata = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'));
} catch {
  process.stderr.write(`The project-local ${name} CLI is not installed. See README.md for the existing dependency locations.\n`);
  process.exit(1);
}

// Version checks are fully offline: no provider initialization, login or telemetry.
if (providedArgs.length === 1 && ['--version', '-V'].includes(providedArgs[0])) {
  process.stdout.write(`${metadata.name} ${metadata.version}\n`);
  process.exit(0);
}

const node = path.join(root, 'agent-runtime/node_modules/node/bin/node');
const entry = typeof metadata.bin === 'string' ? metadata.bin : metadata.bin?.[tool.bin];
if (!entry) {
  process.stderr.write(`No ${tool.bin} executable is declared by the installed package.\n`);
  process.exit(1);
}
try {
  await access(node);
  await access(path.resolve(directory, entry));
} catch {
  process.stderr.write('The project-local Node 24 runtime or CLI executable is missing. See README.md.\n');
  process.exit(1);
}
const child = spawn(node, [path.resolve(directory, entry), ...(providedArgs.length ? providedArgs : ['--help'])], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, PATH: `${path.dirname(node)}${path.delimiter}${process.env.PATH ?? ''}` },
});
child.on('error', error => {
  process.stderr.write(`Could not start ${name}: ${error.message}\n`);
  process.exitCode = 1;
});
child.on('exit', (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0);
});
