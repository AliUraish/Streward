import { defineAgent } from 'eve';

export default defineAgent({
  description: 'Coordinate evidence-backed inspection of the Cedar, Harbor and Juniper properties.',
  model: process.env.STEWARD_EVE_MODEL || 'openai/gpt-6-luna-fast',
  modelContextWindowTokens: 128_000,
  defaultTools: false,
  tool: false,
});
