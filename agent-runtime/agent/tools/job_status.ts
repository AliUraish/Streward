import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { propertyJob } from '../lib/property-api';
export default defineTool({
  description:'Check a real inspection job in its property scope. A receipt or progress message is not proof of completion.',
  inputSchema:z.object({propertyId:z.enum(['cedar','harbor','juniper']),jobId:z.string().min(1)}),
  execute:({propertyId,jobId})=>propertyJob(propertyId,jobId),
});
