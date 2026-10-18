"""Pokémon Regrade Lab: 2012+ research and scenario analysis.
No live PSA/eBay pricing is claimed. Optional Pokémon TCG API is catalog-only.
"""
from __future__ import annotations

import io
import math
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Pokémon Regrade Lab", page_icon="🎴", layout="wide", initial_sidebar_state="expanded")

COLS = ["Card", "Year", "Set", "Number", "PSA 9 purchase ($)", "PSA 9 resale ($)",
        "PSA 10 resale ($)", "PSA 8 resale ($)", "PSA 9 population", "PSA 10 population",
        "Regrade to 10 (%)", "Regrade to 8 (%)", "Grading cost ($)", "Source / notes"]
MONEY = ["PSA 9 purchase ($)", "PSA 9 resale ($)", "PSA 10 resale ($)", "PSA 8 resale ($)", "Grading cost ($)"]
NUMERIC = ["Year", *MONEY, "PSA 9 population", "PSA 10 population", "Regrade to 10 (%)", "Regrade to 8 (%)"]


def blank(name="", year=2021, set_name="", number=""):
    return {"Card": name, "Year": int(year), "Set": set_name, "Number": str(number),
            "PSA 9 purchase ($)": 0.0, "PSA 9 resale ($)": 0.0, "PSA 10 resale ($)": 0.0,
            "PSA 8 resale ($)": 0.0, "PSA 9 population": 0, "PSA 10 population": 0,
            "Regrade to 10 (%)": 10.0, "Regrade to 8 (%)": 5.0, "Grading cost ($)": 200.0,
            "Source / notes": "Prices/populations not yet researched"}


def example_data():
    a = blank("DEMO A — hypothetical only", 2021)
    a.update({"PSA 9 purchase ($)": 1000, "PSA 9 resale ($)": 1000,
              "PSA 10 resale ($)": 10000, "PSA 8 resale ($)": 650, "PSA 9 population": 800,
              "PSA 10 population": 200, "Regrade to 10 (%)": 10, "Regrade to 8 (%)": 5,
              "Grading cost ($)": 600, "Source / notes": "DEMO — all values invented"})
    b = blank("DEMO B — hypothetical only", 2020)
    b.update({"PSA 9 purchase ($)": 1000, "PSA 9 resale ($)": 1000,
              "PSA 10 resale ($)": 2000, "PSA 8 resale ($)": 650, "PSA 9 population": 800,
              "PSA 10 population": 200, "Regrade to 10 (%)": 20, "Regrade to 8 (%)": 5,
              "Grading cost ($)": 200, "Source / notes": "DEMO — all values invented"})
    return pd.DataFrame([a, b], columns=COLS)


def normalized(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=COLS)
    out = df.copy()
    for c in COLS:
        if c not in out:
            out[c] = "" if c in ("Card", "Set", "Number", "Source / notes") else 0
    return out[COLS]


def evaluated(frame, limit, fee_pct, extras, min_profit):
    raw = normalized(frame)
    for c in NUMERIC:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    complete = raw[NUMERIC].notna().all(axis=1)
    nonnegative = raw[NUMERIC].ge(0).all(axis=1)
    probs = (raw["Regrade to 10 (%)"] + raw["Regrade to 8 (%)"] <= 100) & (raw["Regrade to 10 (%)"] <= 100) & (raw["Regrade to 8 (%)"] <= 100)
    years = raw["Year"].between(2012, datetime.now().year + 1) & (raw["Year"] % 1 == 0)
    named = raw["Card"].fillna("").astype(str).str.strip().ne("")
    valid = complete & nonnegative & probs & years & named
    problems = raw.loc[~valid, ["Card", "Year"]].copy()
    clean = raw.loc[valid].copy()
    clean["Budget eligible"] = clean["PSA 9 purchase ($)"].le(limit)
    clean["Research complete"] = clean[MONEY].gt(0).all(axis=1) & ((clean["PSA 9 population"] + clean["PSA 10 population"]) > 0)
    p10 = clean["Regrade to 10 (%)"] / 100
    p8 = clean["Regrade to 8 (%)"] / 100
    p9 = 1 - p10 - p8
    takehome = 1 - fee_pct / 100
    cost = clean["PSA 9 purchase ($)"] + clean["Grading cost ($)"] + extras
    expected_resale = takehome * (p10 * clean["PSA 10 resale ($)"] + p9 * clean["PSA 9 resale ($)"] + p8 * clean["PSA 8 resale ($)"])
    clean["PSA 9/10 population gem share (%)"] = (100 * clean["PSA 10 population"] / (clean["PSA 9 population"] + clean["PSA 10 population"]).replace(0, float("nan"))).round(2)
    clean["Expected net proceeds ($)"] = expected_resale
    clean["Expected profit ($)"] = expected_resale - cost
    clean["Expected ROI (%)"] = (100 * clean["Expected profit ($)"] / cost.replace(0, float("nan")))
    clean["Profit if 10 ($)"] = takehome * clean["PSA 10 resale ($)"] - cost
    clean["Profit if 9 ($)"] = takehome * clean["PSA 9 resale ($)"] - cost
    clean["Profit if 8 ($)"] = takehome * clean["PSA 8 resale ($)"] - cost
    clean["Expected gain vs sell 9 now ($)"] = clean["Expected profit ($)"] - (takehome * clean["PSA 9 resale ($)"] - clean["PSA 9 purchase ($)"])
    base = takehome * ((1 - p8) * clean["PSA 9 resale ($)"] + p8 * clean["PSA 8 resale ($)"])
    improvement = takehome * (clean["PSA 10 resale ($)"] - clean["PSA 9 resale ($)"])
    clean["Break-even P10 (%)"] = 100 * (cost - base) / improvement.replace(0, float("nan"))
    clean["9 → 10 multiplier"] = clean["PSA 10 resale ($)"] / clean["PSA 9 resale ($)"].replace(0, float("nan"))
    eligible = clean[(clean["Budget eligible"]) & (clean["Research complete"]) & (clean["Expected profit ($)"] >= min_profit)].copy()
    return eligible, clean, problems


@st.cache_data(ttl=3600, show_spinner=False)
def catalog_search(q, api_key=""):
    """Official Pokémon TCG API v2 catalog lookup, not a pricing or population source."""
    cleaned = q.replace('"', "").replace("\\", "").strip()
    if len(cleaned) < 2:
        return [], "Enter at least two characters."
    # Phrase search; optionally fall back to a broader token search.
    headers = {"X-Api-Key": api_key} if api_key else {}
    query = f'name:"{cleaned}"'
    try:
        response = requests.get("https://api.pokemontcg.io/v2/cards", params={"q": query, "pageSize": 100, "orderBy": "-set.releaseDate"}, headers=headers, timeout=12)
        response.raise_for_status()
        cards = response.json().get("data", [])
        if not cards and " " in cleaned:
            response = requests.get("https://api.pokemontcg.io/v2/cards", params={"q": f'name:{cleaned.split()[0]}', "pageSize": 100, "orderBy": "-set.releaseDate"}, headers=headers, timeout=12)
            response.raise_for_status()
            cards = response.json().get("data", [])
        cards = [c for c in cards if int((c.get("set") or {}).get("releaseDate", "0000")[:4]) >= 2012]
        return cards, ""
    except requests.RequestException as exc:
        return [], f"Catalog request unavailable: {exc}. You can still add cards manually."
    except (TypeError, ValueError, KeyError) as exc:
        return [], f"Unexpected catalog response: {exc}. Add the card manually."


if "records" not in st.session_state:
    st.session_state.records = example_data()
if "catalog_picked" not in st.session_state:
    st.session_state.catalog_picked = None

st.markdown("""<style>
.block-container{padding-top:1.8rem;max-width:1450px}
[data-testid='stMetricValue']{font-size:1.5rem}
</style>""", unsafe_allow_html=True)
st.title("🎴 Pokémon Regrade Lab")
st.caption("PSA 9 → PSA 10 investment research • 2012 onward • No invented live PSA prices or populations")

with st.sidebar:
    st.header("Your investment rules")
    max_buy = st.number_input("Maximum PSA 9 purchase price", min_value=0.0, value=5000.0, step=100.0, format="%.2f")
    sell_fee = st.number_input("Marketplace selling fee (%)", min_value=0.0, max_value=100.0, value=10.0, step=0.5)
    default_grade = st.number_input("Default PSA grading fee ($)", min_value=0.0, value=200.0, step=25.0)
    extra = st.number_input("Shipping / insurance / other costs per card ($)", min_value=0.0, value=0.0, step=5.0)
    min_ev = st.number_input("Minimum expected profit to show ($)", value=0.0, step=25.0)
    st.divider()
    st.info("**Population gem share ≠ PSA 9 upgrade probability.** Set your own regrade odds after evaluating card condition.")
    st.caption("Grading tiers and declared-value rules change. Enter the appropriate PSA fee for each card; $200 is only an editable default.")

find, research, rankings, guide = st.tabs(["🔎 Find a card", "🧮 Analyze & enter", "🏆 Opportunity rankings", "📖 How it works"])

with find:
    st.subheader("Search the Pokémon catalog")
    st.write("Find a 2012+ card by name using the Pokémon TCG API catalog (when reachable). This identifies the exact printing; it **does not provide live PSA sold prices or PSA populations**.")
    api_key = ""
    try:
        api_key = st.secrets.get("POKEMON_TCG_API_KEY", "")
    except Exception:
        pass
    q = st.text_input("Card name", placeholder="Gengar VMAX or Umbreon", key="lookup")
    if st.button("Search catalog", type="primary", disabled=len(q.strip()) < 2):
        st.session_state.search_value = q.strip()
    if st.session_state.get("search_value"):
        with st.spinner("Searching card catalog..."):
            matches, err = catalog_search(st.session_state.search_value, api_key)
        if err:
            st.warning(err)
        elif not matches:
            st.info("No 2012+ results found. Try a shorter name or add a card manually.")
        else:
            st.caption(f"Showing {len(matches)} results (maximum 100 per search). Refine the name to narrow the results.")
            options = {f'{c.get("name", "Unknown")} | {(c.get("set") or {}).get("name", "Unknown set")} | #{c.get("number", "?")} | {(c.get("set") or {}).get("releaseDate", "")[:4]} | {c.get("id", "")}': c for c in matches}
            chosen = st.selectbox("Select the exact printing", list(options))
            selected = options[chosen]
            left, right = st.columns([1, 3])
            with left:
                url = (selected.get("images") or {}).get("small")
                if url:
                    st.image(url, use_container_width=True)
            with right:
                st.write(f'**{selected.get("name", "")}**')
                st.write(f'Set: {(selected.get("set") or {}).get("name", "")} • Number: {selected.get("number", "")}')
                st.write(f'Released: {(selected.get("set") or {}).get("releaseDate", "Unknown")}')
                if st.button("Add this printing to research list", type="primary"):
                    item = blank(selected.get("name", ""), int((selected.get("set") or {}).get("releaseDate", "2021")[:4]), (selected.get("set") or {}).get("name", ""), selected.get("number", ""))
                    item["Source / notes"] = f'Catalog ID: {selected.get("id", "")} | PSA data unverified'
                    st.session_state.records = pd.concat([st.session_state.records, pd.DataFrame([item])], ignore_index=True)
                    st.success("Added! Open Analyze & enter to research prices, populations, and probabilities.")
    st.divider()
    st.subheader("Can't find it? Add manually")
    with st.form("manual_add", clear_on_submit=True):
        a, b = st.columns([2, 1])
        with a:
            nm = st.text_input("Card name (required)", placeholder="Tyranitar EX")
            sn = st.text_input("Set name", placeholder="XY ...")
        with b:
            yr = st.number_input("Release year", min_value=2012, max_value=datetime.now().year + 1, value=2021, step=1)
            cn = st.text_input("Card number", placeholder="123/xyz")
        submitted = st.form_submit_button("Add manual card")
    if submitted:
        if not nm.strip():
            st.error("Please enter a card name.")
        else:
            st.session_state.records = pd.concat([st.session_state.records, pd.DataFrame([blank(nm.strip(), yr, sn, cn)])], ignore_index=True)
            st.success("Card added to your research list.")

with research:
    st.subheader("Your researched cards")
    st.write("Edit prices, populations, regrade assumptions, and PSA fees directly in the table. Scroll horizontally to see all columns. Rows with missing research stay out of ranked opportunities.")
    with st.expander("What the inputs mean", expanded=False):
        st.markdown("**PSA 9 purchase:** price you could actually pay; **PSA 9/10/8 resale:** your researched expected sale prices; **populations:** PSA counts; **regrade to 10/8:** your estimates for an already-graded PSA 9; **PSA fee:** correct tier based on potential declared value.")
    upload = st.file_uploader("Import your previous or saved research (CSV)", type=["csv"], key="csv")
    if upload is not None:
        try:
            incoming = pd.read_csv(upload, dtype={"Number": str})
            if "Card" not in incoming.columns or "Year" not in incoming.columns:
                st.error("CSV needs at least Card and Year columns. Download the template below.")
            elif st.button("Replace current table with imported CSV"):
                st.session_state.records = normalized(incoming)
                st.success("Import loaded. Check the data before ranking.")
                st.rerun()
        except Exception as exc:
            st.error(f"Import error: {exc}")
    edited = st.data_editor(normalized(st.session_state.records), num_rows="dynamic", hide_index=True, width="stretch", key="research_editor",
                            column_config={"Source / notes": st.column_config.TextColumn("Source / notes", width="large")})
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("💾 Save edits to this session", type="primary"):
            st.session_state.records = normalized(edited)
            st.success("Saved in this browser session. Download a CSV to keep a permanent copy.")
    with c2:
        if st.button("Apply default grading fee to all rows"):
            new = edited.copy()
            new["Grading cost ($)"] = default_grade
            st.session_state.records = normalized(new)
            st.rerun()
    with c3:
        st.download_button("⬇️ Download edited research CSV", normalized(edited).to_csv(index=False).encode("utf-8"), "pokemon_regrade_research.csv", "text/csv")
    st.download_button("Download blank CSV template", pd.DataFrame(columns=COLS).to_csv(index=False).encode("utf-8"), "pokemon_regrade_template.csv", "text/csv")
    st.caption("**Storage note:** free Streamlit Community Cloud can restart. Keep the downloaded CSV as your permanent research backup. Data in the public app is not a secure private database.")

with rankings:
    st.subheader("Rank opportunities")
    st.caption("Only 2012+ cards with positive input prices, PSA populations, valid probabilities, and purchases ≤ your sidebar cap can appear. Sample DEMO rows are fictional.")
    # The analysis uses the saved research table; the editor contains pending changes until saved.
    eligible, all_valid, invalid_rows = evaluated(st.session_state.records, max_buy, sell_fee, extra, min_ev)
    if not invalid_rows.empty:
        st.warning(f"{len(invalid_rows)} row(s) have invalid/missing required values, years, or probabilities. Fix them in Analyze & enter.")
    if not all_valid.empty:
        incomplete = int((~all_valid["Research complete"]).sum())
        over_budget = int((~all_valid["Budget eligible"]).sum())
        if incomplete or over_budget:
            st.info(f"{incomplete} row(s) missing pricing/population research; {over_budget} row(s) over your ${max_buy:,.0f} purchase cap. They are excluded from the rankings.")
    if eligible.empty:
        st.warning("No qualified researched cards yet. Add or import a card and fill its prices, PSA populations, regrade odds, and grading fee, then save edits.")
    else:
        order = st.selectbox("Sort opportunities by", ["Expected profit ($)", "Expected ROI (%)", "Expected gain vs sell 9 now ($)", "9 → 10 multiplier", "Break-even P10 (%)"], index=0)
        ranked = eligible.sort_values(order, ascending=(order == "Break-even P10 (%)"))
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Qualified cards", f"{len(ranked)}")
        k2.metric("Highest expected profit", f'${ranked["Expected profit ($)"].max():,.0f}')
        k3.metric("Positive EV", f'{(ranked["Expected profit ($)"] > 0).sum()}')
        k4.metric("Budget cap per card", f'${max_buy:,.0f}')
        cols = ["Card", "Year", "Set", "Number", "PSA 9 purchase ($)", "PSA 9 resale ($)", "PSA 10 resale ($)", "Regrade to 10 (%)", "Regrade to 8 (%)", "PSA 9/10 population gem share (%)", "Grading cost ($)", "Expected profit ($)", "Expected ROI (%)", "Expected gain vs sell 9 now ($)", "Break-even P10 (%)", "Profit if 10 ($)", "Profit if 9 ($)", "Profit if 8 ($)", "Source / notes"]
        st.dataframe(ranked[cols].round(2), hide_index=True, width="stretch")
        st.download_button("⬇️ Download rankings CSV", ranked.round(4).to_csv(index=False).encode("utf-8"), "pokemon_regrade_rankings.csv", "text/csv")
        st.divider()
        pick = st.selectbox("Inspect a card's outcomes", list(ranked.index), format_func=lambda idx: f'{ranked.loc[idx,"Card"]} — {ranked.loc[idx,"Set"]} #{ranked.loc[idx,"Number"]}')
        target = ranked.loc[pick]
        p10 = float(target["Regrade to 10 (%)"])
        p8 = float(target["Regrade to 8 (%)"])
        st.bar_chart(pd.DataFrame({"Estimated probability (%)": [p8, 100-p10-p8, p10]}, index=["PSA 8", "PSA 9", "PSA 10"]))
        a,b,c = st.columns(3)
        a.metric("PSA 10 profit", f'${target["Profit if 10 ($)"]:,.0f}')
        b.metric("PSA 9 profit", f'${target["Profit if 9 ($)"]:,.0f}')
        c.metric("PSA 8 profit", f'${target["Profit if 8 ($)"]:,.0f}')
        st.write(f'**Break-even chance of PSA 10:** {target["Break-even P10 (%)"]:.1f}% (holding your PSA 8 probability fixed).')
        st.caption("Negative break-even percentages mean the modeled trade is profitable even at 0% PSA 10; above 100% means it cannot break even under these assumptions. Prices and odds are user estimates, not predictions or verified live sales.")

with guide:
    st.subheader("The math and data policy")
    st.markdown("""
**Expected net sale proceeds** = (1 − selling fee) × [P(10) × PSA 10 price + P(9) × PSA 9 price + P(8) × PSA 8 price].

**Expected profit** = expected net sale proceeds − actual PSA 9 purchase − PSA grading fee − other costs.

**Expected ROI** = expected profit / (purchase + grading + other costs).

**Expected gain vs selling the 9 now** compares regrading with immediately selling the purchased PSA 9 on the same marketplace. This matters because a regrade can have positive total EV while being worse than simply reselling the 9.

**Break-even P(10)** holds your P(8) fixed, allocates all remaining outcomes to P(9), and solves for zero expected profit. It is **not** the probability of a 10.

**PSA gem share** is calculated as population 10 / (population 9 + population 10). It is not the chance of an already-graded PSA 9 upgrading. The model never substitutes population share for your estimated regrade odds.

### What is and is not automated
- **Card identity**: optional free Pokémon TCG API catalog lookup; card images/set/year/number are catalog metadata, not evidence of an actual slab's condition.
- **PSA 9 and PSA 10 sold prices**: **manual input** at this stage; use recent confirmed sales and verify variants/languages.
- **PSA population counts**: **manual input** at this stage; check the PSA Population Report for the exact variety.
- **PSA service fee**: **manual per card**; PSA value limits, turnaround and pricing may change or cause upcharges. A $200 default is not a live fee quote.
- **Regrade probability**: **your estimate**; a card cracking from PSA 9 can return PSA 8, 9, 10, altered, or have other outcomes; the model's three-grade simplification does not capture every possible outcome.
- **Data persistence**: browser session only; export your research CSV frequently. No real-money transactions are executed.

The app does not automatically make buying decisions. If the PSA 10 value is very high, check declared-value tiers and any potential upcharge before trusting expected profit.
""")
    st.markdown("[Pokémon TCG API documentation](https://docs.pokemontcg.io/) · [PSA Population Report](https://www.psacard.com/pop) · [PSA Services & Pricing](https://www.psacard.com/services)")
