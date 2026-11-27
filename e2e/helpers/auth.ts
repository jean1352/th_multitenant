import { randomUUID } from 'node:crypto';
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { execCompose } from './docker';

export type AdminCredentials = {
  email: string;
  password: string;
};

export function getAdminCredentials(workerIndex: number): AdminCredentials {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!email?.trim() || !password?.trim()) {
    throw new Error('Define E2E_ADMIN_EMAIL y E2E_ADMIN_PASSWORD en .env.test antes de ejecutar las pruebas.');
  }

  const parts = email.trim().split('@');
  const [local, domain] = parts;
  if (!local || !domain || parts.length !== 2) {
    throw new Error('E2E_ADMIN_EMAIL debe contener un correo válido para generar las cuentas de pruebas.');
  }
  const suffix = `+e2e-w${workerIndex}-${randomUUID()}`;
  // El límite de la parte local de un correo es de 64 caracteres.
  return { email: `${local.slice(0, 64 - suffix.length)}${suffix}@${domain}`, password };
}

export async function prepareAdmin(admin: AdminCredentials): Promise<void> {
  // Transmitir las credenciales de esta prueba sin incluirlas en los argumentos.
  await execCompose([
    'exec', '-T', '--env', 'E2E_ADMIN_EMAIL', '--env', 'E2E_ADMIN_PASSWORD',
    'web-test', 'python', 'docker/create_e2e_admin.py',
  ], 20_000, {
    ...process.env,
    E2E_ADMIN_EMAIL: admin.email,
    E2E_ADMIN_PASSWORD: admin.password,
  });
}

export async function cleanupAdmin(admin: AdminCredentials): Promise<void> {
  await execCompose([
    'exec', '-T', 'web-test', 'python', 'docker/cleanup_e2e_admin.py', admin.email,
  ], 20_000);
}

export async function authenticateAdmin(page: Page, admin: AdminCredentials): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Correo Institucional').fill(admin.email);
  await page.getByLabel('Contraseña').fill(admin.password);

  await page.getByRole('button', { name: 'Iniciar Sesión', exact: true }).click();

  // Esperar la redirección real del login antes de entregar la página al test.
  await expect(page).toHaveURL('/recruitment/dashboard');
  await expect(
    page.getByRole('heading', { name: 'Dashboard de Gestión', exact: true }),
  ).toBeVisible();
}
