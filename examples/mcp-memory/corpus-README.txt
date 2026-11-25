line 1: empty entity name
line 2: null name (control: zod rejects this one)
line 3: observations wrong type (control: zod rejects this one)
line 4: unknown top-level key: zod strips it silently
line 5: unknown key inside an entity: stripped, not rejected
line 6: numbers instead of strings (control: zod rejects this one)
line 7: zero entities: z.array() accepts empty by default
line 8: missing required entities key (control: zod rejects this one)
line 9: 10k-char entity name: no max length in the zod source
line 10: 5000 empty-string observations: no maxItems, no minLength on items
