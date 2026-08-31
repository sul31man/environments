# Engagement scoring: specification

This describes what the service is for and what each published quantity means. It is
written the way the desk describes its own model, in business terms.

**It does not give formulas.** Where a definition could reasonably be written more than one
way, the published reference run is the authority: `reference/scores_reference.csv`,
`reference/feature_profile.csv` and `reference/feature_sample.csv` are what the service
produced, and a correct rebuild reproduces them.

---

## 1. What the service does

Members rate films. For each new rating the service publishes an **engagement** score, the
modelled chance that the member took to the film, and a **promote** flag for the ones the
editorial desk should surface in next week's recommendations.

A run reads the export, fits on the **fit window**, and scores the **score window**, both
taken from the run configuration and inclusive of the last second of their end date.
Ratings are processed in `rating_id` order.

## 2. What counts as engagement

A rating counts as engagement when the member gave the film four stars or better.

## 3. The rule that governs every historical quantity

Everything the service knows about a member, a film, or a member's taste in a kind of film
is built from **ratings made strictly before the rating being scored**, and never from
ratings later than the end of the fit window.

That is what the service could actually have known at the moment the rating landed. A
quantity that looks at the rating it is describing, or at anything that happened after it,
is not a prediction.

The score window may sit inside the fit window. That does not relax the rule.

## 4. What the features mean

Thirty two features are published, in the order `src/engagement/assemble.py` declares them.

**When.** The hour, weekday and month the rating was made, whether it fell at a weekend,
and how far into the scored stretch it sits.

**Who.** From the membership record: gender, age band, occupation, and the broad region the
member registered from.

**What.** From the catalogue: the year the film was released, how old it was when rated, how
many genres it carries and whether it carries more than one.

**The member's record.** How many ratings they had behind them, how many of those were
engagements, the rate at which they engage, the average stars they award, how long they had
been rating by then, and how often they rate per day of that tenure. Also whether the member
was new to the service at that moment.

**The film's record.** The same idea for the film: how many ratings it had collected, how
many were engagements, the rate at which it draws them, the average stars it earns, and how
long it had been drawing ratings. Also whether the film was new at that moment.

**Taste.** How many times the member had rated films of this film's leading genre before,
and the rate at which they engaged with them.

**Standing.** How the member's engagement rate, the film's engagement rate, and the member's
average stars sit against the portfolio, and how the member's taste for this genre sits
against their own overall rate.

**Thin history.** A rate built on very little history is unreliable, so it is pulled toward
the portfolio rate in proportion to how little history stands behind it;
`encoding.smoothing` sets how hard. The same treatment gives the member rate, the film rate
and the genre rate.

## 5. Members and films with no history

Members join continuously, so a live run scores ratings from members the fit window never
saw, and occasionally films it never saw either.

- A **count** of past activity is zero where there was none.
- Anything the service **averages or spreads over history** is undefined rather than zero,
  and is carried at the **portfolio level** for that quantity: the same measure taken across
  the fit window as a whole. For a rate, that is the portfolio engagement rate.

None of those averages may be carried at zero. A zero engagement rate reads to the desk as a
member who reliably dislikes everything, which is the opposite of what a brand new member
means.

## 6. Model

Logistic regression over the thirty two features, fitted on the fit window against
engagement, with the features standardised to zero mean and unit variance first, fitted on
the fit window. Values that are not finite are treated as zero before standardising. The
estimator uses the `lbfgs` solver with `model.regularisation` as its inverse regularisation
strength, `model.max_iter` iterations and `model.seed`.

## 7. Output

One row per scored rating, in `rating_id` order, carrying `rating_id`, `member_id`,
`film_id`, `rated_at`, `engagement` and `promote`.

`engagement` is the modelled probability, rounded to six decimal places. `promote` is 1 when
the unrounded score is at least `scoring.promote_threshold`.

A run also writes a summary beside the scores. The summary is not graded.
