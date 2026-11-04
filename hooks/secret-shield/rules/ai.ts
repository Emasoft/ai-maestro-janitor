// AI provider keys. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const anthropicKey: Rule = { kind: 'anthropic-key', pattern: /\b(sk-ant-[A-Za-z0-9_-]{20,})/g, group: 1 }
export const openaiProjectKey: Rule = { kind: 'openai-key', pattern: /\b(sk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,})/g, group: 1 }
export const openaiLegacyKey: Rule = { kind: 'openai-key', pattern: /\b(sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})\b/g, group: 1 }
export const openaiKey48: Rule = { kind: 'openai-key', pattern: /\b(sk-[A-Za-z0-9]{48})\b/g, group: 1 }
export const huggingfaceToken: Rule = { kind: 'huggingface-token', pattern: /\b(hf_[A-Za-z0-9]{34,})\b/g, group: 1 }
