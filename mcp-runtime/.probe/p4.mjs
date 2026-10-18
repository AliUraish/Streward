import { inputRequired } from '@modelcontextprotocol/server';
console.log(JSON.stringify(inputRequired({ inputRequests: { decision: inputRequired.elicit({ message: 'm', requestedSchema: { type: 'object', properties: { choice: { type: 'string', enum: ['a','b'] } }, required: ['choice'] } }) } })));
