# BlogAuto Duplication Rubric

## 1. Purpose

This rubric defines how BlogAuto distinguishes acceptable similarity from problematic duplication.

It should be used by both:

- topic approval logic
- final article similarity checks

The rubric separates topic duplication from expression duplication because those risks behave differently.

## 2. Duplication Axes

### 2.1 Topic Duplication

Topic duplication happens when two articles solve the same user job in nearly the same way even if wording differs.

Signals:

- same keyword or near-synonym keyword
- same intent core
- same promised outcome
- same procedural route

### 2.2 Expression Duplication

Expression duplication happens when sentence flow, paragraph order, phrase family, or section arrangement are too similar even if keywords differ.

Signals:

- same lead frame
- same structural order
- same transition sequence
- high sentence overlap
- high masked structural similarity

## 3. Decision Bands

### 3.1 Complete Duplicate

Treat as complete duplicate when one or more of the following holds:

- normalized title is effectively identical
- keyword, intent, and promised outcome all match
- lexical similarity is very high and structural similarity is also high
- multiple paragraphs appear as near-copy segments

Operational rule:

- reject immediately
- regenerate with a new topic or new article plan

Suggested thresholds:

- title similarity `>= 0.95`
- lexical similarity `>= 0.82`
- structural similarity `>= 0.72`

### 3.2 Strong Similarity

Treat as strong similarity when the topic is close or the writing frame is too close, but the draft is not an outright copy.

Signals:

- same problem and same solution ordering
- same lead and ending family
- structural similarity is high after unique tokens are masked
- title is not identical but makes the same promise

Operational rule:

- rewrite first, do not discard immediately
- change structure slot and style slot together
- re-check after rewrite

Suggested thresholds:

- lexical similarity `0.70-0.81`
- structural similarity `0.62-0.71`

### 3.3 Acceptable Similarity

Treat as acceptable similarity when some overlap is natural because the domain overlaps, but the article still delivers a meaningfully different user experience.

Signals:

- same software family but different task outcome
- same topic family but different reader intent
- same advice class but different section ordering and examples

Operational rule:

- allow output
- add soft penalty if recent history is concentrated

Suggested thresholds:

- lexical similarity `0.50-0.69`
- structural similarity `0.45-0.61`

### 3.4 Distinct

Treat as distinct when both topic route and expression route differ enough to avoid reader fatigue.

Operational rule:

- accept with no duplication penalty

Suggested thresholds:

- lexical similarity `< 0.50`
- structural similarity `< 0.45`

## 4. Topic Duplication Judgment Table

Judge topic duplication using these four questions:

1. Is the user trying to achieve the same end result?
2. Is the core action path the same?
3. Is the promise made by the title effectively the same?
4. Would a reader feel they read the same solution twice?

Decision guide:

- `4 yes`: complete duplicate
- `3 yes`: strong similarity
- `2 yes`: review with expression score
- `0-1 yes`: topic is likely distinct

## 5. Expression Duplication Judgment Table

Judge expression duplication using these five questions:

1. Does the lead use the same opening move?
2. Does the body follow the same section order?
3. Do transition families appear in the same sequence?
4. Does the ending deliver the same CTA or wrap-up move?
5. Do multiple sentences remain similar after masking unique tokens?

Decision guide:

- `4-5 yes`: strong similarity or complete duplicate
- `3 yes`: rewrite recommended
- `0-2 yes`: acceptable if topic is distinct

## 6. Borderline Cases

### 6.1 Same Topic, Different Reader Job

Allow when:

- keyword overlaps but the article solves a different job
- examples, sequencing, and promised outcome differ clearly

Example idea:

- same software feature
- one article explains setup
- another article explains troubleshooting

This should not be treated as complete duplication.

### 6.2 Different Topic, Same Writing Skeleton

Do not hard block immediately.

If only the skeleton matches:

- apply structure penalty
- apply style or rhythm penalty
- rewrite with a different slot mix if threshold is exceeded

### 6.3 Same Title Family, Different Value

If titles share a family pattern but not the same promise, treat it as a soft risk, not an instant duplicate.

Example:

- "실무 작업 흐름 가이드"
- "반복 업무 표준화 방법"

If the body route and user outcome differ, this is a penalty issue, not a hard-block issue.

## 7. Sources to Compare Against

The first operating version should compare against:

- `automation/data/previous_posts.csv`
- `automation/data/topic_used.csv`
- archived text files under `automation/output`
- current batch outputs generated in the same run

## 8. Recommended Implementation Mapping

Use the rubric with the current script stack like this:

- title duplication check against `topic_used.csv`
- body similarity check with `similarity_checker.py`
- structural similarity check with masked-token comparison
- recent-history concentration check using slot metadata logs

## 9. Practical Operating Rule

When uncertain, prefer this order:

1. block only obvious duplicates
2. rewrite strong similarity
3. allow acceptable similarity with penalty logging

The system should optimize for controlled diversity, not artificial uniqueness at the cost of throughput.
