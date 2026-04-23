---
labels:
- latest
- production
name: relevance_score
type: text
---

Return JSON only.

Idea:
Title: {{idea_title}}
Description: {{idea_description}}
Keywords: {{idea_keywords}}

Paper:
Title: {{paper_title}}
Abstract: {{paper_abstract}}

Task:
Evaluate how relevant the paper is to the idea on a 0-10 scale.

Guidelines:
- 0-3: not relevant
- 4-6: weak or partial relevance
- 7-8: relevant
- 9-10: highly relevant and directly useful

Be strict: only assign 8+ if the paper clearly advances or strongly relates to the idea.

IMPORTANT: Write the reasoning field in Russian.

Return a JSON object with:
- relevance_score
- reasoning
- key_concepts_matched
