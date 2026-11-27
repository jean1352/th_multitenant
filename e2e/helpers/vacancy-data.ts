import { randomUUID } from 'node:crypto';
import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { execCompose } from './docker';

type Catalogo = { id: number; name: string };
type RecursoVacante = 'sede' | 'area' | 'cargo' | 'proceso' | 'motivo' | 'responsable';
export type VacancyResourceIds = Partial<Record<RecursoVacante, number>>;

export type DatosVacante = {
  titulo: string;
  descripcion: string;
  sede: Catalogo;
  area: Catalogo;
  cargo: Catalogo;
  proceso: Catalogo;
  etapas: Catalogo[];
  motivo: Catalogo;
  responsable: { id: number; full_name: string };
};

export async function createVacancyData(
  request: APIRequestContext,
  ids: VacancyResourceIds,
): Promise<DatosVacante> {
  const codigo = randomUUID();

  async function crear<T extends { id: number }>(
    url: string,
    data: Record<string, unknown>,
    recurso?: RecursoVacante,
  ): Promise<T> {
    const response = await request.post(url, { data });
    await expect(response, `Preparar datos E2E: ${url}`).toBeOK();
    const resultado = await response.json() as T;
    // Registrar cada recurso al crearlo para poder limpiar si falla el siguiente.
    if (recurso) ids[recurso] = resultado.id;
    return resultado;
  }

  const sede = await crear<Catalogo>('/organization/api/sedes', {
    name: `Sede E2E ${codigo}`,
  }, 'sede');
  const area = await crear<Catalogo>('/organization/api/areas', {
    name: `Área E2E ${codigo}`,
    sede_id: sede.id,
    responsible_email: `responsable-${codigo}@example.com`,
  }, 'area');
  const cargo = await crear<Catalogo>('/organization/api/positions', {
    name: `Cargo E2E ${codigo}`,
    area_id: area.id,
  }, 'cargo');
  const responsable = await crear<DatosVacante['responsable']>('/api/users', {
    email: `responsable-${codigo}@example.com`,
    full_name: `Responsable E2E ${codigo}`,
    password: `E2e-${codigo}`,
    role: 'th',
    is_active: true,
    sede_id: sede.id,
    area_id: area.id,
  }, 'responsable');
  const proceso = await crear<Catalogo>('/recruitment/api/processes', {
    name: `Proceso E2E ${codigo}`,
  }, 'proceso');
  const etapas: Catalogo[] = [];
  for (const [indice, nombre] of ['Revisión de perfil', 'Entrevista'].entries()) {
    etapas.push(await crear<Catalogo>(`/recruitment/api/processes/${proceso.id}/stages`, {
      name: nombre,
      sla_days: 2,
      owner: indice === 0 ? 'reclutador' : 'area',
      order_index: indice + 1,
      responsible_id: responsable.id,
    }));
  }
  const motivo = await crear<Catalogo>('/recruitment/api/config/hiring-reasons', {
    name: `Motivo E2E ${codigo}`,
  }, 'motivo');

  return {
    titulo: `Vacante E2E ${codigo}`,
    descripcion: 'Perfil de prueba para validar la creación de una vacante.',
    sede, area, cargo, proceso, etapas, motivo, responsable,
  };
}

export async function cleanupVacancyData(ids: VacancyResourceIds): Promise<void> {
  // No existe una API para eliminar vacantes. Limpiar solo los IDs propios
  // mediante el backend E2E, incluso si falla la preparación o la prueba.
  if (Object.keys(ids).length > 0) {
    await execCompose([
      'exec', '-T', 'web-test', 'python',
      'docker/cleanup_e2e_vacancy_data.py', JSON.stringify(ids),
    ], 20_000);
  }
}
