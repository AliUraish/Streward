import { defineAgent } from 'eve';
export default defineAgent({
  description: 'Inspect and maintain evidence for Juniper only. Use this specialist for its named property.',
  model: process.env.STEWARD_EVE_MODEL || 'openai/gpt-6-luna-fast',
  modelContextWindowTokens: 128_000,
  defaultTools: false,
});
