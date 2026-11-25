line 1: empty thought string: no minLength
line 2: boolean as a STRING: coercedBoolean union accepts it, model is never told its string became a bool
line 3: unknown key: stripped silently
line 4: thoughtNumber 0: min(1) holds, control
line 5: thoughtNumber -5: min(1) holds, control
line 6: thoughtNumber 1e9: min(1) but NO max
line 7: thoughtNumber as a numeric STRING: z.coerce.number() accepts it
line 8: totalThoughts 0: min(1) holds, control
line 9: missing required nextThoughtNeeded: zod rejects, control
line 10: thought = 10k chars: no maxLength
