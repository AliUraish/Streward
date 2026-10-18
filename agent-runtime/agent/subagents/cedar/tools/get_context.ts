import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { propertyApi } from '../../../lib/property-api';
export default defineTool({
  description: 'Read the current Cedar workspace, requirements, component condition, evidence and recent activity.',
  inputSchema: z.object({}),
  execute: () => propertyApi('cedar'),
});
