import { test as base } from '@playwright/test';
import type { Page } from '@playwright/test';
import { authenticateAdmin, cleanupAdmin, getAdminCredentials, prepareAdmin } from './helpers/auth';
import type { AdminCredentials } from './helpers/auth';
import { checkE2ETarget } from './helpers/docker';
import { cleanupVacancyData, createVacancyData } from './helpers/vacancy-data';
import type { DatosVacante, VacancyResourceIds } from './helpers/vacancy-data';

type Fixtures = {
  destinoE2E: void;
  admin: AdminCredentials;
  paginaAdmin: Page;
  datosVacante: DatosVacante;
};

export const test = base.extend<Fixtures>({
  destinoE2E: [async ({ baseURL }, use) => {
    await checkE2ETarget(baseURL);
    await use();
  }, { auto: true }],

  admin: async ({}, use, testInfo) => {
    const credentials = getAdminCredentials(testInfo.workerIndex);
    try {
      await prepareAdmin(credentials);
      await use(credentials);
    } finally {
      // Los fixtures dependientes limpian sus datos antes de eliminar la cuenta.
      await cleanupAdmin(credentials);
    }
  },

  paginaAdmin: async ({ page, admin }, use) => {
    await authenticateAdmin(page, admin);
    await use(page);
  },

  datosVacante: async ({ paginaAdmin }, use) => {
    const ids: VacancyResourceIds = {};
    try {
      const datos = await createVacancyData(paginaAdmin.request, ids);
      await use(datos);
    } finally {
      await cleanupVacancyData(ids);
    }
  },
});

export { expect } from '@playwright/test';
