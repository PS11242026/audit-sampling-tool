"""Step 9: record testing results (in-app grid or re-import of the completed
Excel pack) and evaluate: MUS Stringer bound or classical projections."""

import streamlit as st

from core import sampling_service
from core.formatting import inr
from reports import excel_pack
from ui.common import money_cols_config, require_engagement

_EDIT_COLS = ["item_id", "date", "doc_no", "account", "narration",
              "book_value", "is_top_stratum", "result", "audited_value",
              "wp_ref", "remarks"]


def _show_results(res: dict, method: str):
    if method == "mus":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Most likely misstatement",
                  inr(res["most_likely_misstatement"]))
        c2.metric("Projected overstatement", inr(res["projected_over"]))
        c3.metric("Upper misstatement limit",
                  inr(res["upper_misstatement_limit"]))
        c4.metric("Tolerable misstatement",
                  inr(res["tolerable_misstatement"]))
        st.caption(f"Basic precision {inr(res['basic_precision'])} + "
                   f"incremental allowance "
                   f"{inr(res['incremental_allowance'])}; top-stratum "
                   f"overstatement {inr(res['top_stratum_over'])}; "
                   f"understatements (reported separately) projected "
                   f"{inr(res['projected_under'])}; "
                   f"{res['errors_lower_over']} overstatement error(s) in "
                   f"the lower stratum at {res['confidence']:.0%} "
                   f"confidence.")
        if res["acceptable"]:
            st.success("UML <= tolerable misstatement: the population is "
                       "acceptable at the planned confidence level "
                       "(SA 530.12).")
        else:
            st.error("UML EXCEEDS tolerable misstatement: extend "
                     "procedures, request adjustment, or reassess risk "
                     "(SA 530.12-13).")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Ratio projection", inr(res["ratio_projection"]))
        c2.metric("Difference projection", inr(res["difference_projection"]))
        attr = res.get("attribute", {})
        c3.metric("Achieved upper deviation limit",
                  f"{attr.get('achieved_upper_limit', 0):.2%}")
        st.caption(f"Sample misstatement {inr(res['sample_misstatement'])} "
                   f"over book value {inr(res['sample_book_value'])}; "
                   f"{attr.get('deviations', 0)} exception(s) in "
                   f"{res['items_tested']} items; tolerable deviation rate "
                   f"{attr.get('tolerable_rate', 0):.2%} at "
                   f"{res['confidence']:.0%} confidence.")
        verdicts = []
        if "acceptable" in res:
            verdicts.append("projection within tolerable misstatement"
                            if res["acceptable"] else
                            "projection EXCEEDS tolerable misstatement")
        if attr:
            verdicts.append("deviation rate acceptable" if
                            attr.get("acceptable") else
                            "deviation rate NOT acceptable at this "
                            "confidence")
        if verdicts and all(("EXCEEDS" not in v and "NOT" not in v)
                            for v in verdicts):
            st.success("; ".join(verdicts))
        elif verdicts:
            st.error("; ".join(verdicts))


def render(user):
    st.header("9. Results & evaluation")
    eng = require_engagement()
    if not eng:
        return
    eid = eng["id"]
    samples = sampling_service.list_samples(eid)
    active = samples[samples["status"].isin(["draft", "final"])] \
        if len(samples) else samples
    if not len(active):
        st.info("Generate samples first (step 6).")
        return

    ids = active["id"].tolist()
    labels = {int(r.id): (f"S{r.id}  {r.category}  ({r.method}, "
                          f"n={r.n_selected}, {r.status})")
              for r in active.itertuples(index=False)}
    sid = int(st.selectbox("Sample", ids, format_func=lambda i: labels[int(i)]))

    tab_enter, tab_import = st.tabs(
        ["Enter results in-app", "Import completed Excel pack"])

    with tab_enter:
        items = sampling_service.get_sample_items(sid)
        st.caption("Mark each item Pass/Exception; for misstatements enter "
                   "the audited value (misstatement = book - audited is "
                   "computed). Blank audited value = book value.")
        edited = st.data_editor(
            items[_EDIT_COLS], hide_index=True, key=f"results_{sid}",
            column_config={
                "item_id": st.column_config.NumberColumn(disabled=True),
                "date": st.column_config.TextColumn(disabled=True),
                "doc_no": st.column_config.TextColumn(disabled=True),
                "account": st.column_config.TextColumn(disabled=True),
                "narration": st.column_config.TextColumn(disabled=True,
                                                         width="large"),
                "book_value": st.column_config.NumberColumn(
                    disabled=True, format="localized"),
                "is_top_stratum": st.column_config.CheckboxColumn(
                    disabled=True),
                "result": st.column_config.SelectboxColumn(
                    options=["", "Pass", "Exception"]),
                "audited_value": st.column_config.NumberColumn(
                    format="localized"),
            })
        if st.button("Save results", type="primary", key=f"save_{sid}"):
            n = sampling_service.save_results(sid, edited, user)
            st.success(f"Saved results for {n} items.")

    with tab_import:
        st.caption("Upload the workpaper pack after filling the Result / "
                   "Audited value columns on the sample tabs - the hidden "
                   "_meta sheet maps tabs back to samples.")
        up = st.file_uploader("Completed workpaper pack (.xlsx)",
                              type=["xlsx"], key="results_up")
        if up and st.button("Import results from workbook"):
            try:
                parsed = excel_pack.read_results_workbook(up.getvalue())
            except ValueError as e:
                st.error(str(e))
                parsed = {}
            eng_ids = set(int(i) for i in samples["id"].tolist())
            done = 0
            for s_id, df in parsed.items():
                if int(s_id) in eng_ids:
                    done += sampling_service.save_results(int(s_id), df,
                                                          user)
            st.success(f"Imported results for {done} items across "
                       f"{len(parsed)} sample(s).")

    st.subheader("Evaluate")
    if st.button("Run evaluation", type="primary", key=f"eval_{sid}"):
        try:
            res = sampling_service.evaluate_sample(sid, user)
            method = sampling_service.get_sample(sid)["method"]
            _show_results(res, method)
        except ValueError as e:
            st.error(str(e))
    else:
        prior = sampling_service.latest_evaluation(sid)
        if prior:
            st.caption(f"Latest evaluation {prior['created_at']} by "
                       f"{prior['created_by']}:")
            _show_results(prior["results"],
                          sampling_service.get_sample(sid)["method"])
