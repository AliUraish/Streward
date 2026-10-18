import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { propertyJob } from '../../../lib/property-api';
export default defineTool({
  description: 'Read a real Cedar job. Rejects jobs belonging to other properties.',
  inputSchema: z.object({jobId:z.string().min(1)}),
  execute: ({jobId}) => propertyJob('cedar',jobId),
});
