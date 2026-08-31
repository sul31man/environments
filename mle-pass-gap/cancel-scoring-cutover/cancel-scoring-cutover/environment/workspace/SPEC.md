# Return risk scoring: specification

This describes what the service is for and what each published quantity means. It is
written the way the desk describes its own model, in business terms.

**It does not give formulas.** Where a definition could reasonably be written more than one
way, the published reference run is the authority: `reference/scores_reference.csv`,
`reference/feature_profile.csv` and `reference/feature_sample.csv` are what the service
produced, and a correct rebuild reproduces them.

---

## 1. Run shape

A run reads the export, fits on the **fit window** and scores the **score window**, both
taken from the run configuration and inclusive of the last second of their end date.

Lines are processed in `line_id` order. Everything the service knows about a product, an
account or a market is learned from the **fit window only**. The score window is never used
to fit anything.

## 2. The label

A line counts as a return if a credit note is later raised against the same account for the
same product, within `labelling.window_days` days of the line. Credits raised before the
line, or later than that, do not count.

## 3. What the features mean

Forty features are published, in the order `src/riskscore/assemble.py` declares them.

**Calendar.** When the line was placed: hour, day of week, month, week of year, whether it
fell at a weekend, and how far into the scored period it sits.

**Basket.** The order the line belongs to: how many lines it carries, how many units, what
it is worth, this line's share of that value, how many different products it covers, the
largest share any single line takes, and the average value of a line on it.

**Product history.** What the fit window knows about the product: how often it was ordered,
how many units moved, its typical price, how much that price varied around its own typical
level, the width of the band it traded in, how fast it has been selling once short-run noise
is smoothed out, how many separate days it traded on, and how long before the end of the fit
window it last traded. Also, from the catalogue, how old the listing was when the line was
placed and whether the line predates the listing at all.

**Account history.** The same idea for the buyer: tenure at the time of the line, whether
the line carries an account, how many lines and units the account has behind it, how long
before the end of the fit window it last ordered, how regularly it orders, the month it
spends most in and whether this line falls in that month.

**Price position.** How the line's price compares with the product's typical price, and with
the typical price in its market.

**Return propensity.** How often the account and the product have been returned before, both
as counts and as a rate. A rate over thin history is unreliable, so it is pulled toward the
portfolio rate in proportion to how little history stands behind it; `encoding.smoothing`
sets how hard. The same treatment gives the product rate, the market rate and the account
rate. Seasonality is the average return rate for the calendar month the line falls in.

**Segment.** A coarse behavioural grouping, described in section 5.

## 4. Products and markets with no history

The catalogue turns over, so a live run scores lines for products the fit window never
traded, and markets it never traded in.

- A **count** of past activity is zero where there was none.
- Anything the service **averages or spreads over history** is undefined rather than zero,
  and is carried at the **portfolio average**: the same quantity averaged over the keys that
  do have history. For a rate, that is the portfolio rate.
- The **-1** marker is used only for the three age-and-tenure quantities, where it means the
  line has no such date to measure from.

None of the averages may be carried at zero. A zero reads to the warehouse as a settled, low
risk line and sends it out unvetted, which is the failure this model exists to prevent.

**The published reference run cannot show you this.** Its window sits inside the fit window,
where every product and market already has history.

## 5. Segmentation

`f_segment` is a k-means grouping over four of the published features, standardised to zero
mean and unit variance with the standardisation fitted on the fit window. Values that are
not finite are treated as zero before standardising. It is fitted on the fit window with
`segmentation.n_segments` groups and `segmentation.seed`, from ten independent starts,
keeping the tightest result.

Group numbers are **canonical**: they do not depend on which start won, and the same
behaviour always carries the same number. The reference sample shows which number goes with
which behaviour.

## 6. Model

Logistic regression over the forty features, fitted on the fit window against the label,
with the features standardised to zero mean and unit variance first, fitted on the fit
window. Values that are not finite are treated as zero before standardising. The estimator
uses the `lbfgs` solver with `model.regularisation` as its inverse regularisation strength,
`model.max_iter` iterations and `model.seed`.

## 7. Output

One row per scored line, in `line_id` order, carrying `line_id`, `order_id`, `sku`,
`placed_at`, `risk_score` and `hold`.

`risk_score` is the modelled probability that the line is returned, rounded to six decimal
places. `hold` is 1 when the unrounded score is at least `scoring.hold_threshold`.

A run also writes a summary beside the scores. The summary is not graded.
