import { test, expect } from './fixtures';

test('Create a new vacancy', async ({ paginaAdmin, datosVacante }) => {
  await paginaAdmin.goto('/recruitment/vacancies?scope=all');
  await paginaAdmin.getByRole('button', {
    name: 'Nueva Vacante',
    exact: true,
  }).click();

  const modal = paginaAdmin.getByRole('dialog');
  await expect(modal).toBeVisible();

  await modal.getByLabel('Título de la Publicación').fill(datosVacante.titulo);
  await modal.getByLabel('Sede').selectOption(String(datosVacante.sede.id));
  await modal.getByLabel('Área Solicitante').selectOption(String(datosVacante.area.id));
  await modal.getByLabel('Cargo / Puesto (Estructura)').selectOption(String(datosVacante.cargo.id));
  await modal.getByLabel('Proceso de Selección').selectOption(String(datosVacante.proceso.id));
  await modal.getByLabel('Motivo de Contratación').selectOption(String(datosVacante.motivo.id));
  await modal.getByLabel('Responsable / Reclutador').selectOption(String(datosVacante.responsable.id));
  await modal.getByLabel('Es aumento de dotación (Nuevo puesto)').check();
  await modal.getByLabel('Descripción / Perfil').fill(datosVacante.descripcion);
  await modal.getByRole('button', { name: 'Guardar' }).click();

  await expect(paginaAdmin.getByText("Vacante creada")).toBeVisible();
  await expect(modal).not.toBeVisible();
  await expect(paginaAdmin.getByText(datosVacante.titulo)).toBeVisible();
});
