import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { propertyApi } from '../lib/property-api';
export default defineTool({
  description:'Read the latest scoped property state, assets, source-linked requirements, events and active job. Use before making property decisions.',
  inputSchema:z.object({propertyId:z.enum(['cedar','harbor','juniper'])}),
  execute:({propertyId})=>propertyApi(propertyId),
});
