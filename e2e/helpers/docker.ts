import { execFile } from 'node:child_process';
import { resolve } from 'node:path';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const projectRoot = resolve(__dirname, '../..');

export function execCompose(args: string[], timeout = 10_000, env?: NodeJS.ProcessEnv) {
  return execFileAsync('docker', ['compose', ...args], { cwd: projectRoot, timeout, env });
}

export async function checkE2ETarget(baseURL: string | undefined): Promise<void> {
  if (!baseURL) throw new Error('Falta la baseURL del entorno E2E.');
  const destino = new URL(baseURL);
  if (
    destino.protocol !== 'http:' ||
    !['localhost', '127.0.0.1', '[::1]'].includes(destino.hostname) ||
    destino.pathname !== '/' || destino.search || destino.hash ||
    destino.username || destino.password
  ) {
    throw new Error('Los fixtures E2E requieren una URL raíz HTTP local de web-test, sin credenciales ni parámetros.');
  }

  const { stdout } = await execCompose(['port', 'web-test', '8000']);
  const puertos = stdout.trim().split(/\r?\n/).map(line => line.match(/:(\d+)$/)?.[1]);
  if (!puertos.includes(destino.port || '80')) {
    throw new Error(
      `PLAYWRIGHT_BASE_URL debe apuntar al puerto publicado de web-test (${puertos.filter(Boolean).join(', ')}). ` +
      'Se detuvo la prueba antes de preparar datos.',
    );
  }

  // Comprobar la base del mismo servicio que ejecutará la preparación y limpieza.
  await execCompose(['exec', '-T', 'web-test', 'python', 'docker/check_e2e_target.py']);
}
