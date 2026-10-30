// Explicit, non-overwriting destinations for browser verification evidence.
const fs = require('node:fs');
const path = require('node:path');

function resolvedDestination(input) {
  const absolute = path.resolve(input);
  let ancestor = absolute;
  const tail = [];
  while (!fs.existsSync(ancestor)) {
    const parent = path.dirname(ancestor);
    if (parent === ancestor) throw new Error('No existing ancestor: ' + absolute);
    tail.unshift(path.basename(ancestor));
    ancestor = parent;
  }
  if (tail.length && !fs.statSync(ancestor).isDirectory()) throw new Error('Destination ancestor is not a directory: ' + ancestor);
  return path.join(fs.realpathSync(ancestor), ...tail);
}

const within = (child, parent) => {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
};

function prepareEvidence(root, argv = process.argv.slice(2)) {
  const options = {};
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i];
    if (!['--out', '--runtime-dir'].includes(flag) || options[flag] || !argv[i + 1] || argv[i + 1].startsWith('--')) {
      throw new Error('Usage: node <check-script> --out <new-evidence-directory> --runtime-dir <new-runtime-directory>');
    }
    options[flag] = argv[i + 1];
  }
  if (!options['--out'] || !options['--runtime-dir']) throw new Error('Both --out and --runtime-dir are required; historical destinations are never defaults.');
  const output = resolvedDestination(options['--out']);
  const runtime = resolvedDestination(options['--runtime-dir']);
  const protectedPaths = ['day09', 'day10'].map(name => resolvedDestination(path.join(root, 'docs/test-results', name)));
  // Validate all destinations before creating either one. Reject symlink aliases too.
  for (const destination of [output, runtime]) {
    if (protectedPaths.some(protectedPath => within(destination, protectedPath) || within(protectedPath, destination))) {
      throw new Error('Refusing protected historical evidence destination: ' + destination);
    }
    if (fs.existsSync(destination)) {
      if (!fs.statSync(destination).isDirectory() || fs.readdirSync(destination).length) {
        throw new Error('Refusing existing nonempty/non-directory destination: ' + destination);
      }
    }
  }
  if (within(output, runtime) || within(runtime, output)) throw new Error('Evidence and runtime directories must be separate, non-nested destinations.');
  for (const destination of [output, runtime]) fs.mkdirSync(destination, { recursive: true });
  console.log('Evidence directory: ' + output);
  console.log('Runtime directory: ' + runtime);
  return { output, runtime };
}

module.exports = { prepareEvidence };
