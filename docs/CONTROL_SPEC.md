# BlogAuto Content Quality Control Spec

## 1. Purpose

This document defines the first operating version of the BlogAuto content quality control system.

The system has three goals:

1. Prevent hard-fail content risks such as direct duplication, forbidden phrases, and title collisions.
2. Disperse repeated structure, rhythm, and tone through penalty-based scoring instead of binary rejection.
3. Leave enough logs to explain why a draft passed, was rewritten, or was held for review.

This spec is written for the current BlogAuto pipeline and should align with:

- `automation/scripts/refine_drafts_ai.py`
- `automation/scripts/similarity_checker.py`
- `automation/scripts/run_blog_pipeline.py`
- `automation/data/topic_used.csv`
- `automation/data/qa_used.csv`

## 2. Evaluation Unit

The control system evaluates one generated article as a bundle of five units:

1. `title`
2. `lead`
3. `body_structure`
4. `body_expression`
5. `ending`

The system also separates duplication into two categories:

- `topic duplication`: the same user intent, same action, or same solution path appears again even if wording changes.
- `expression duplication`: wording, sentence shape, transitions, or paragraph order are too similar even if the topic is not identical.

## 3. Control Layers

The system must use three layers in order.

### 3.1 Hard Block

Hard block stops output immediately and sends the draft to regeneration.

Use hard block only for cases that should not be negotiated:

- exact title match against existing output or registered topic history
- near-copy content from `previous_posts.csv`, saved outputs, or topic output archive
- forbidden phrases or restricted wording defined by policy
- unresolved placeholder text, prompt leakage, or generation artifacts
- malformed article missing required sections

### 3.2 Penalty Distribution

Penalty rules do not instantly fail the draft.

They add weighted points when repetition risk increases in:

- structure
- sentence rhythm
- transition habits
- style slot reuse
- ending pattern reuse

This layer exists to avoid overfitting the generator to a single allowed pattern.

### 3.3 Guided Selection

Before generation or rewrite, the pipeline should select variation slots on purpose:

- structure slot
- lead slot
- rhythm slot
- style slot
- CTA or ending slot

Guided selection reduces repeated output before similarity checks even run.

## 4. Hard Block Rules

The initial hard block set should stay narrow.

### 4.1 Title Hard Block

Block when one of the following is true:

- exact normalized title match with a title in `topic_used.csv`
- exact normalized title match with a file already written in `automation/output`
- title differs only by punctuation, bracket style, or spacing

Initial rule:

- normalized title similarity `>= 0.95`: block

### 4.2 Body Duplication Hard Block

Block when one of the following is true:

- `similarity_checker.compare_texts()` score exceeds the hard duplicate threshold
- large sentence-set overlap indicates direct copying
- repeated paragraph order and phrase reuse together indicate near-copy behavior

Initial rule:

- lexical similarity `>= 0.82`: block
- structural similarity `>= 0.72` and lexical similarity `>= 0.68`: block

### 4.3 Forbidden Output Hard Block

Block when one of the following is true:

- unresolved markers such as `TODO`, `TBD`, bracket instructions, or model notes remain
- platform-specific banned phrases appear
- legal or trust-risk wording appears without approval
- article is too short to satisfy minimum delivery quality

Initial rule:

- any forbidden phrase match: block
- article body under minimum word or character floor: block

## 5. Penalty Model

The penalty model accumulates points across dimensions.

Suggested initial total score:

- `total_penalty = structure + rhythm + style + transition + ending + duplication_soft`

Suggested operating thresholds:

- `0-29`: pass
- `30-49`: pass with log flag
- `50-69`: rewrite recommended
- `70+`: mandatory regeneration

## 6. Penalty Dimensions

### 6.1 Structure Penalty

Apply points when the article repeats the same section ordering or same paragraph role pattern as recent outputs.

Examples:

- same lead-to-list-to-tip-to-summary shape used too often
- same number of sections with same functional role
- repeated FAQ insertion at the same position

Initial weights:

- same top-level structure slot as one of the last 3 outputs: `+15`
- same top-level structure slot as 2 or more of the last 5 outputs: `+25`
- same ending slot combined with same structure slot: additional `+10`

### 6.2 Rhythm Penalty

Apply points when sentence length pattern and paragraph tempo are too repetitive.

Examples:

- most paragraphs start with short declarative lines
- all sections use the same 2-sentence cadence
- consecutive outputs share the same average sentence length band

Initial weights:

- same rhythm slot as last output: `+10`
- average sentence length within narrow repeated band for 3 outputs: `+10`
- repeated paragraph count pattern within same structure slot: `+8`

### 6.3 Style Penalty

Apply points when diction and narrative stance stay too similar.

Examples:

- repeated tutorial voice with the same reassurance pattern
- repeated phrase families such as "쉽게 배우는", "실무 작업 흐름", "바로 적용"
- same metaphor or framing habit

Initial weights:

- same style slot as 2 consecutive outputs: `+12`
- recurring opening phrase family: `+8`
- recurring ending phrase family: `+8`

### 6.4 Transition Penalty

Apply points when transition expressions cluster too heavily.

Examples:

- repeated use of "먼저", "다음", "마지막으로" in the same sequence
- repeated section openers across multiple posts

Initial weights:

- same transition sequence in lead and first two sections: `+8`
- same transition family repeated across 3 recent outputs: `+12`

### 6.5 Soft Duplication Penalty

Apply points before hard block when content is not a direct copy but is trending too close.

Initial weights:

- lexical similarity `0.60-0.69`: `+15`
- lexical similarity `0.70-0.81`: `+30`
- structural similarity `0.55-0.61`: `+10`
- structural similarity `0.62-0.71`: `+20`

## 7. Decision Rules

The system should decide in this order:

1. Run hard block rules.
2. If any hard block triggers, regenerate immediately.
3. If hard block passes, calculate penalty total.
4. If penalty total exceeds threshold, rewrite with a new slot combination.
5. If only style is similar but topic is distinct, prefer rewrite over discard.

Initial decision logic:

- hard block count `>= 1`: regenerate
- total penalty `>= 70`: regenerate
- total penalty `50-69`: rewrite once with new structure and style slots
- total penalty `< 50`: accept

## 8. Rewrite Policy

Rewrite should not be random.

When a draft is rewritten, the system should change at least:

- one structure slot
- one lead or ending slot
- one rhythm or style slot

Recommended rewrite limits:

- maximum rewrite attempts per draft: `3`
- after the third failed attempt: hold and log for manual review

## 9. Logging Spec

Every evaluated article should produce a structured record.

Minimum log fields:

- `run_id`
- `topic_id`
- `platform`
- `title`
- `structure_slot`
- `lead_slot`
- `rhythm_slot`
- `style_slot`
- `ending_slot`
- `hard_block_flags`
- `penalty_structure`
- `penalty_rhythm`
- `penalty_style`
- `penalty_transition`
- `penalty_ending`
- `penalty_duplication_soft`
- `total_penalty`
- `best_similarity_score`
- `best_structural_score`
- `decision`
- `decision_reason`
- `rewrite_attempt`
- `created_at`

Recommended output file:

- `automation/data/content_quality_log.csv`

## 10. Rollout Order

The first implementation pass should follow this order:

1. structure slot tracking
2. rhythm slot tracking
3. style slot tracking
4. duplication rubric binding
5. penalty calculation
6. logging and threshold tuning

This order matters because forcing duplication checks first can sharply reduce generation volume and make root-cause tuning harder.

## 11. Initial Threshold Notes

These values are intentionally conservative.

They should be tuned only after enough log samples are collected from real runs.

Start with:

- narrow hard block scope
- broader penalty collection
- rewrite-first behavior for style-only similarity

The first success condition is not perfect uniqueness.
The first success condition is stable diversity without collapsing article throughput.
