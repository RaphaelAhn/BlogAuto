# BlogAuto Diversity Rulebook

## 1. Purpose

This rulebook defines how BlogAuto intentionally spreads article shape, pacing, and tone before duplication becomes a hard failure.

The guiding rule is simple:

- do not rely on a single forbidden pattern list
- rotate through approved slots
- penalize concentration instead of banning normal reuse

## 2. Structure Distribution Rules

### 2.1 Structure Slots

The system should begin with six structure slots.

1. `problem_to_solution`
2. `checklist_walkthrough`
3. `mistake_fix_pattern`
4. `comparison_then_choice`
5. `workflow_breakdown`
6. `faq_plus_summary`

Each article must declare exactly one primary structure slot.

### 2.2 Structure Slot Use Rule

Do not let one slot dominate recent output.

Initial distribution rules:

- no single slot should exceed `2` uses in the last `5` outputs per platform
- no single slot should exceed `4` uses in the last `12` outputs globally
- if a slot is used in the previous output, deprioritize it for the next output

### 2.3 Section Role Variants

Even inside one structure slot, section roles should vary.

Available section-role moves:

- context first
- quick answer first
- example first
- warning first
- setup first

Penalty trigger examples:

- same slot plus same role opener in 2 consecutive outputs
- same section count and same role order in 3 of the last 5 outputs

## 3. Lead Pattern Rules

### 3.1 Lead Slots

Start with five lead slots.

1. `pain_point_open`
2. `outcome_preview_open`
3. `common_mistake_open`
4. `scenario_open`
5. `question_open`

Each output should use one lead slot.

### 3.2 Lead Rotation Rule

Initial rules:

- same lead slot cannot repeat more than `2` times in the last `5` outputs per platform
- same first-sentence family should not repeat in consecutive outputs

Repeated lead examples to penalize:

- two consecutive leads beginning with a reassurance phrase
- three recent leads using the same question frame

## 4. Rhythm Penalty Rules

### 4.1 Rhythm Slots

Start with four rhythm slots.

1. `short_punchy`
2. `balanced_explainer`
3. `long_then_short`
4. `stepwise_even`

Each output should use one rhythm slot.

### 4.2 Rhythm Detection

Rhythm can be estimated from:

- average sentence length
- sentence length variance
- paragraph sentence count
- ratio of short to long sentences

### 4.3 Rhythm Penalties

Apply penalties when:

- the same rhythm slot repeats in consecutive outputs
- three recent outputs fall into the same sentence-length band
- body paragraphs keep the same count and cadence across outputs

Suggested initial penalties:

- consecutive rhythm slot repeat: `+10`
- same sentence-length band for 3 outputs: `+10`
- same cadence map plus same structure slot: `+12`

## 5. Style Slot Rules

### 5.1 Style Slots

Start with six style slots.

1. `coach_practical`
2. `calm_manual`
3. `field_note`
4. `efficiency_focus`
5. `beginner_supportive`
6. `decision_helper`

Each output should use one primary style slot.

### 5.2 Style Slot Rotation

Initial rules:

- same style slot should not appear in more than `2` of the last `4` outputs per platform
- if the same style slot is paired with the same structure slot twice in a row, force a different style next time

### 5.3 Phrase Family Control

Track reusable phrase families instead of banning exact lines only.

Examples of phrase families to track:

- "쉽게 시작"
- "실무에서 바로"
- "먼저 확인"
- "마지막으로 정리"
- "헷갈리기 쉬운 부분"

Penalty trigger:

- same phrase family appears in opening or ending zones across consecutive outputs

## 6. Transition Sequence Rules

Track transition families used in the lead and first major sections.

Examples:

- sequence A: `먼저 -> 다음 -> 마지막으로`
- sequence B: `보통 -> 하지만 -> 그래서`
- sequence C: `예를 들어 -> 이때 -> 정리하면`

Rules:

- same sequence should not repeat in consecutive outputs
- if a transition family repeats in 3 recent outputs, deprioritize it strongly

## 7. CTA and Ending Distribution Rules

### 7.1 Ending Slots

Start with four ending slots.

1. `quick_recap`
2. `action_prompt`
3. `mistake_watchout`
4. `next_step_guidance`

### 7.2 Ending Rules

Initial rules:

- same ending slot cannot repeat more than `2` times in the last `5` outputs per platform
- same ending slot plus same structure slot in consecutive outputs adds extra penalty
- same CTA phrase family in consecutive outputs adds penalty even if wording is slightly changed

## 8. Slot Selection Policy

Slot selection should be guided, not random-only.

Recommended priority order:

1. pick the least-used valid structure slot
2. pick a lead slot not used recently with that structure
3. pick a rhythm slot that breaks the last output pattern
4. pick a style slot that does not recreate the previous pairing
5. pick an ending slot that breaks the recent CTA pattern

If all preferred options are blocked by recent history, use the lowest-penalty available combination.

## 9. Minimal Metadata to Save

For each output, save:

- `structure_slot`
- `lead_slot`
- `rhythm_slot`
- `style_slot`
- `ending_slot`
- `section_count`
- `avg_sentence_length`
- `transition_signature`
- `opening_phrase_family`
- `ending_phrase_family`

This metadata is enough to begin practical penalty scoring without a heavy NLP pipeline.
