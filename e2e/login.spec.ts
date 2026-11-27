import { test, expect } from './fixtures';

test('login as admin', async ({ page, admin }) => {
  await page.goto('/login');
  await page.getByLabel('Correo Institucional').fill(admin.email);
  await page.getByLabel('Contraseña').fill(admin.password);
  await page.getByRole('button', { name: 'Iniciar Sesión', exact: true }).click();

  await expect(page).toHaveURL('/recruitment/dashboard');
  await expect(
    page.getByRole('heading', { name: 'Dashboard de Gestión', exact: true }),
  ).toBeVisible();
});
