import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Pokémon Regrade Analyzer", page_icon="📈", layout="wide")
st.title("Pokémon PSA 9 → PSA 10 Analyzer")
st.caption("Manual research MVP • Not connected to live eBay sales or PSA population data")

with st.sidebar:
    st.header("Assumptions")
    max_purchase = st.number_input("Maximum PSA 9 purchase price ($)", min_value=0.0, value=5000.0, step=100.0)
    sell_fee_pct = st.number_input("Selling fee (%)", min_value=0.0, max_value=100.0, value=10.0, step=0.5)
    default_grading = st.number_input("Default regrading cost ($)", min_value=0.0, value=200.0, step=25.0)
    extra_cost = st.number_input("Other costs per card ($)", min_value=0.0, value=0.0, step=5.0)
    st.info("PSA service tier fees can change and may depend on declared value. Enter the appropriate fee for each card below.")

st.markdown("Enter researched card prices and **estimated regrade probabilities**. PSA population ratios are displayed separately and are **not** assumed to be the odds of upgrading an existing PSA 9.")

cols = ["Card", "PSA 9 purchase ($)", "PSA 9 resale ($)", "PSA 10 resale ($)", "PSA 8 resale ($)", "PSA 9 population", "PSA 10 population", "Regrade to 10 (%)", "Regrade to 8 (%)", "Grading cost ($)"]
if "cards" not in st.session_state:
    st.session_state.cards = pd.DataFrame([
        ["Example A (hypothetical)", 1000, 1000, 10000, 650, 800, 200, 10, 0, 600],
        ["Example B (hypothetical)", 1000, 1000, 2000, 650, 800, 200, 20, 0, 200],
    ], columns=cols)

uploaded = st.file_uploader("Import a CSV of cards (optional)", type="csv")
if uploaded is not None:
    try:
        imported = pd.read_csv(uploaded)
        if set(cols).issubset(imported.columns):
            st.session_state.cards = imported[cols].copy()
            st.success("CSV loaded. Review the table before calculating.")
        else:
            st.error("CSV must contain the same column headers as the downloadable template.")
    except Exception as e:
        st.error(f"Could not read CSV: {e}")

edited = st.data_editor(st.session_state.cards, num_rows="dynamic", hide_index=True, use_container_width=True, key="editor")

if st.button("Apply default grading fee to every row"):
    edited["Grading cost ($)"] = default_grading
    st.session_state.cards = edited.copy()
    st.rerun()

if st.button("Calculate and rank cards", type="primary"):
    st.session_state.cards = edited.copy()

cards = st.session_state.cards.copy()
if cards.empty:
    st.warning("Add at least one card above.")
    st.stop()

numeric = cols[1:]
for col in numeric:
    cards[col] = pd.to_numeric(cards[col], errors="coerce")
cards = cards.dropna(subset=numeric).copy()
if cards.empty:
    st.warning("Enter numeric values for each required field.")
    st.stop()

invalid = (cards[numeric] < 0).any(axis=1) | (cards["Regrade to 10 (%)"] + cards["Regrade to 8 (%)"] > 100) | (cards["Regrade to 10 (%)"] > 100) | (cards["Regrade to 8 (%)"] > 100)
if invalid.any():
    st.error("Some rows have negative amounts or probabilities above 100%. Correct them before using the results.")
    cards = cards.loc[~invalid].copy()

cards = cards[cards["PSA 9 purchase ($)"] <= max_purchase].copy()
if cards.empty:
    st.warning("No valid cards fit your maximum PSA 9 purchase budget.")
    st.stop()

p10 = cards["Regrade to 10 (%)"] / 100
p8 = cards["Regrade to 8 (%)"] / 100
p9 = 1 - p10 - p8
fee_multiplier = 1 - sell_fee_pct / 100
cards["PSA 9/10 population gem share (%)"] = (100 * cards["PSA 10 population"] / (cards["PSA 9 population"] + cards["PSA 10 population"]).replace(0, float('nan'))).round(1)
cards["Expected net resale ($)"] = fee_multiplier * (p10 * cards["PSA 10 resale ($)"] + p9 * cards["PSA 9 resale ($)"] + p8 * cards["PSA 8 resale ($)"])
cards["Expected profit ($)"] = cards["Expected net resale ($)"] - cards["PSA 9 purchase ($)"] - cards["Grading cost ($)"] - extra_cost
cards["Expected ROI (%)"] = 100 * cards["Expected profit ($)"] / (cards["PSA 9 purchase ($)"] + cards["Grading cost ($)"] + extra_cost).replace(0, float('nan'))
# Break-even probability keeping user-selected PSA 8 chance constant; other outcomes become PSA 9.
base_net = fee_multiplier * ((1 - p8) * cards["PSA 9 resale ($)"] + p8 * cards["PSA 8 resale ($)"])
upside = fee_multiplier * (cards["PSA 10 resale ($)"] - cards["PSA 9 resale ($)"])
needed = (cards["PSA 9 purchase ($)"] + cards["Grading cost ($)"] + extra_cost - base_net) / upside.replace(0, float('nan'))
cards["Break-even P(10) (%)"] = (100 * needed).round(1)
cards["PSA 9→10 multiple"] = (cards["PSA 10 resale ($)"] / cards["PSA 9 resale ($)"].replace(0, float('nan'))).round(2)

st.subheader("Opportunity rankings")
sort = st.selectbox("Rank by", ["Expected profit ($)", "Expected ROI (%)", "PSA 9→10 multiple"])
ranked = cards.sort_values(sort, ascending=False)
st.dataframe(ranked.round(2), use_container_width=True, hide_index=True)
st.caption("Break-even P(10) can be negative or above 100%, indicating the model is profitable even without a 10, or cannot break even with the stated assumptions. It holds the PSA 8 probability fixed.")

c1,c2,c3 = st.columns(3)
c1.metric("Cards within budget", len(ranked))
c2.metric("Highest expected profit", f"${ranked['Expected profit ($)'].max():,.2f}")
c3.metric("Positive-EV cards", int((ranked["Expected profit ($)"] > 0).sum()))

st.download_button("Download ranked results (CSV)", data=ranked.to_csv(index=False).encode("utf-8"), file_name="regrade_rankings.csv", mime="text/csv")
st.download_button("Download input template (CSV)", data=st.session_state.cards[cols].head(0).to_csv(index=False).encode("utf-8"), file_name="pokemon_cards_template.csv", mime="text/csv")
st.warning("Important: Regrade success probabilities must be estimated independently; PSA population share is not a reliable individual PSA 9 upgrade probability. Enter realistic PSA fees, and account for downgrade, damage, shipping, insurance, price fluctuations, and the possibility of failing to recover a PSA 9 grade.")
