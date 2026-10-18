import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { propertyApi } from '../../../lib/property-api';
export default defineTool({
  description: 'Start an actual persisted Cedar evidence inspection. Read job status to verify completion; do not claim to perform physical inspection.',
  inputSchema: z.object({scope:z.string().default('all')}),
  execute: ({scope},ctx) => propertyApi('cedar','inspections',{scope},ctx.session),
});
