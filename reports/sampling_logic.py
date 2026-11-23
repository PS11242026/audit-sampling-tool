"""Sampling methodology / basis-of-selection PDF (SA 530).

A standalone note that documents *how* the tool turns the analysis run
(step 5) into sampling populations and *how* each sample size and selection
is derived - the formulas, factors, seeds and reproducibility guarantees -
followed by the actual plans on record for this engagement. Offered as a
download in step 6 so the methodology travels with the working papers.

The reference factor tables are computed live from ``core.sampling.factors``
so they always match the numbers the tool actually uses.
"""

from core import materiality, risk, sampling_service
from core.formatting import inr, short_hash
from core.sampling.factors import (EXPANSION_FACTORS, expansion_factor,
                                    reliability_factor)
from core.version import APP_NAME, __version__
from reports.pdf_memo import METHOD_LABELS, METHOD_RATIONALE, _Memo
from storage import auditlog, db

_FACTOR_LABELS = {
    "size": "Monetary size vs performance materiality",
    "prior_qualification": "Prior-year qualification area",
    "regulatory": "SERC-regulated revenue",
    "control": "Control environment",
    "complexity": "Accounting complexity (Ind AS)",
    "volume": "Transaction volume",
    "new_oneoff": "New account / one-off item",
}


def generate_sampling_logic(engagement_id: int, user: dict) -> bytes:
    eng = db.get_engagement(engagement_id)
    if not eng:
        raise ValueError("engagement not found")
    cfg = risk.load_config(engagement_id)
    th = cfg["thresholds"]
    fw = cfg["factor_weights"]
    mat = materiality.load(engagement_id)
    pops = risk.get_populations(engagement_id)
    samples = sampling_service.list_samples(engagement_id)
    active = samples[samples["status"] != "superseded"] \
        if len(samples) else samples

    pm = float(mat.get("performance") or 0) if mat else 0.0
    isl = float(mat.get("isl_cutoff") or 0) if mat else 0.0

    pdf = _Memo(eng, doc_title="Audit Sampling Methodology (SA 530)")
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font(pdf.family_name, "B", 14)
    pdf.multi_cell(0, 7, pdf.tx("Audit Sampling Methodology and Basis of "
                                "Selection"))
    pdf.ln(2)
    pdf.kv([
        ("Engagement", eng["name"]),
        ("Company", eng["company"]),
        ("Financial year", f"{eng['fy_start']} to {eng['fy_end']}"),
        ("Regulatory context", eng.get("control_period") or "-"),
        ("Prepared with", f"{APP_NAME} v{__version__}"),
        ("Engagement master seed", str(eng["master_seed"])),
        ("Generated at / by", f"{db.now()} / {user.get('username', '')} "
                              f"({user.get('role', '')})"),
    ])

    # ---------------------------------------------------------------- 1
    pdf.h1("1. Purpose")
    pdf.para(
        "This note records the sampling logic the tool applies for this "
        "engagement: how the SA 315 analysis run (step 5) splits each "
        "population into items examined in full and a residual sampling "
        "population, how the SA 530 sample size is computed, and how items "
        "are selected. Every selection is seeded and reproducible so it can "
        "be regenerated from the audit file (SA 230). It complements the "
        "sampling memorandum and Excel workpaper pack (step 10).")

    # ---------------------------------------------------------------- 2
    pdf.h1("2. From the analysis run to a sampling population")
    pdf.para(
        "Each categorized population is scored from 1 to 10 on seven "
        "weighted risk factors. The score is a weighted average of the "
        "per-factor scores; a manual weight, where set for a category, "
        "overrides the computed score. The factors and their weights for "
        "this engagement are:")
    pdf.table(
        ["Risk factor", "Weight"],
        [(_FACTOR_LABELS.get(f, f), f"{float(w):g}") for f, w in fw.items()],
        [140, 40])
    pdf.para(
        f"The final score selects a strategy against configurable thresholds "
        f"(this engagement: full at >= {float(th['full_min']):g}, sample at "
        f">= {float(th['sample_min']):g}):", size=9.5)
    pdf.kv([
        ("FULL (100% verification)",
         f"score >= {float(th['full_min']):g} - the whole category is "
         f"examined in full."),
        ("HYBRID",
         "score in the FULL band but a category value cutoff is set and the "
         "preferred method is not 'full': items at or above the cutoff are "
         "examined 100%, the remainder is sampled."),
        ("SAMPLE",
         f"score >= {float(th['sample_min']):g} and below the full "
         f"threshold - sampled by the category's preferred method."),
        ("SAMPLE_LOW",
         f"score below {float(th['sample_min']):g} - a small random sample "
         f"with a floor of {int(th['low_floor_n'])} items."),
    ])
    pdf.para(
        f"Independently of the category strategy, two kinds of item are "
        f"always routed to 100% verification: individually significant items "
        f"at or above the SA 320 cutoff "
        f"({inr(isl) if isl else 'once materiality is set'}), and "
        f"abnormal-side (contra) entries flagged by the analytics. The "
        f"sampling population for a category is therefore the items that were "
        f"not routed to 100% and that carry a non-zero absolute amount; MUS "
        f"further requires strictly positive amounts.")

    # ---------------------------------------------------------------- 3
    pdf.h1("3. Populations and strategies for this engagement")
    if len(pops):
        short_method = {"mus": "MUS", "stratified": "Stratified",
                        "systematic": "Systematic", "random": "Random",
                        "full": "100%"}
        rows = []
        for p in pops.itertuples(index=False):
            method = cfg["categories"].get(p.category, {}).get(
                "preferred_method", "mus")
            rows.append((p.category[:34], f"{p.final_score:g}", p.strategy,
                         f"{p.txn_count:,}", f"{p.full_count:,}",
                         f"{p.sample_count:,}", inr(p.sample_value),
                         short_method.get(method, method)))
        pdf.table(
            ["Population", "Score", "Strategy", "Items", "100%", "Sampled",
             "Sampled value", "Method"],
            rows, [52, 11, 20, 15, 13, 15, 26, 24])
    else:
        pdf.para("The analysis run (step 5) has not been performed yet, so "
                 "no populations are available.")

    # ---------------------------------------------------------------- 4
    pdf.h1("4. Sample size determination (SA 530.7)")
    pdf.h2("Monetary unit sampling (MUS)")
    pdf.para(
        "n = ceil( BV x RF(C, 0) / ( TM - EM x EF ) ), where BV is the book "
        "value of the sampling population, TM the tolerable misstatement "
        "(defaulting to performance materiality), EM the expected "
        "misstatement, RF(C, 0) the Poisson reliability factor at confidence "
        "C for zero expected errors, and EF the expansion factor for expected "
        "misstatement. The sampling interval is BV / n; any item at or above "
        "the interval is certain to be selected and is examined in full (the "
        "top stratum). If EM x EF reaches TM the tool declines to size a "
        "sample and directs the auditor to extend substantive procedures "
        "instead.")
    pdf.h2("Attribute sampling (tests of controls / compliance)")
    pdf.para(
        "The size is the smallest n for which observing k deviations still "
        "supports 'true rate <= tolerable rate' at confidence C under the "
        "exact binomial distribution, i.e. P(X <= k | n, tolerable rate) <= "
        "1 - C. The allowed deviations k are increased until the expected "
        "deviations in the resulting sample (n x expected rate) do not exceed "
        "k. For a finite population of N items the size is reduced by the "
        "finite population correction n' = ceil( n / (1 + n/N) ). This "
        "reproduces the published AICPA/ICAI attribute tables.")
    pdf.h2("Reference factors (computed by the tool)")
    rf_rows = [(f"{int(c * 100)}%",)
               + tuple(f"{reliability_factor(c, k):.2f}" for k in range(4))
               for c in (0.90, 0.95, 0.99)]
    pdf.table(["Confidence", "RF k=0", "RF k=1", "RF k=2", "RF k=3"],
              rf_rows, [40, 35, 35, 35, 35])
    ef_rows = [(f"{int(c * 100)}%", f"{expansion_factor(c):.2f}")
               for c in (0.90, 0.95, 0.99) if c in EXPANSION_FACTORS]
    pdf.table(["Confidence", "Expansion factor"], ef_rows, [60, 50])

    # ---------------------------------------------------------------- 5
    pdf.h1("5. Selection algorithms")
    pdf.para(
        "Before any selection the population is placed in a documented "
        "canonical order - a stable sort by posting date, document number "
        "then row id - so the same population always presents items in the "
        "same sequence. The random number generator is numpy's PCG64 "
        "(default_rng) seeded with an integer derived from the engagement "
        "master seed: SHA-256 of the master seed, category and generation "
        "number, truncated to 32 bits. A Manager or Partner may enter a prior "
        "seed to redraw an identical selection.")
    pdf.kv([
        ("Monetary unit sampling",
         "Items are laid on a cumulative-value line; with a fixed interval "
         "j = BV / n and a seeded random start in [0, j), a hit is placed at "
         "start + k*j and the item spanning each hit is selected. Items >= j "
         "are the top stratum (100%)."),
        ("Stratified",
         "Value bands are cut at boundaries giving roughly equal cumulative "
         "value; the total sample is allocated across bands proportionally to "
         "band value (default) or count, at least one per non-empty band and "
         "capped at band size; within each band selection is simple random "
         "with a per-band derived seed (SA 530 A8-A9)."),
        ("Systematic",
         "Interval = population / n with a seeded random start, then every "
         "interval-th item. The tool flags SA 530 A13: confirm the "
         "population is not ordered with a period matching the interval."),
        ("Simple random",
         "Every item has an equal chance of selection, with or without "
         "replacement; when n reaches the population size the selection is a "
         "census."),
    ])

    # ---------------------------------------------------------------- 6
    pdf.h1("6. Reproducibility and integrity (SA 230)")
    pdf.para(
        "Each selection is tied to its population by a SHA-256 hash over the "
        "identifying columns (row id, date, document number, account, "
        "absolute amount). Given the same population, seed and size, the "
        "selection is bit-for-bit identical on any machine. Regenerating a "
        "sample supersedes the previous one and records the seed, parameters, "
        "population hash and a required justification in the audit trail, so "
        "the full history of what was tested is preserved.")

    # ---------------------------------------------------------------- 7
    pdf.h1("7. Sampling plans on record")
    if len(active):
        for s in active.itertuples(index=False):
            detail = sampling_service.get_sample(int(s.id))
            payload = detail["payload"]
            params = payload.get("params", {})
            info = payload.get("info", {})
            popstats = payload.get("population", {})
            pdf.h2(f"S{s.id} - {s.category}")
            pairs = [
                ("Method", METHOD_LABELS.get(s.method, s.method)),
                ("Population", f"{popstats.get('count'):,} items, "
                               f"{inr(popstats.get('book_value'))}"),
                ("Sample size", f"{s.n_selected} items selected "
                                f"(generation {s.generation_no}, "
                                f"status {s.status})"),
                ("Seed / algorithm", f"{s.seed} / numpy PCG64, canonical "
                                     f"sort: date, doc no, row id"),
                ("Population SHA-256", short_hash(detail["dataset_sha256"],
                                                  20)),
            ]
            if s.method == "mus":
                pairs += [
                    ("Confidence",
                     f"{float(params.get('confidence', 0.95)) * 100:.0f}%"),
                    ("Tolerable / expected misstatement",
                     f"{inr(params.get('tolerable'))} / "
                     f"{inr(params.get('expected', 0))}"),
                    ("Sampling interval", inr(info.get("interval"))),
                ]
            if s.justification:
                pairs.append(("Regeneration justification", s.justification))
            pdf.kv(pairs)
            pdf.para(METHOD_RATIONALE.get(s.method, ""))
    else:
        pdf.para("No samples have been generated for this engagement yet. "
                 "Generate a sample above to record its parameters, seed and "
                 "population hash here.")

    # ---------------------------------------------------------------- 8
    pdf.h1("8. Sign-off")
    for who in ("Prepared by (Staff/Manager)", "Reviewed by (Manager)",
                "Approved by (Partner)"):
        pdf.para(f"{who}:  Name ____________________  Signature "
                 f"____________________  Date ____________", size=9.5)

    content = bytes(pdf.output())
    auditlog.log(user, "EXPORT_SAMPLING_LOGIC",
                 details={"bytes": len(content)},
                 engagement_id=engagement_id)
    return content
