"""Rebuild the Tableau data source from the raw IEA file.

Usage:  python src/build_dataset.py

Reproduces, as one script, the team's data preparation notebook (notebooks/01_data_preparation.ipynb):
  1. load the IEA Global EV Data Explorer 2026 (long format, 49,176 rows)
  2. clean: restore the unit of price rows, label rows without a geography "Unattributed",
     drop 15 exact duplicates (after checking no key has conflicting values)
  3. standardise names (USA -> United States, Korea -> South Korea, ...), flag country vs aggregate,
     map every country to an IEA region
  4. charging points: add empty rows only for INTERNAL reporting gaps (not before a country's first year)
  5. reshape long -> wide: one row per location-year (Master_Analytical), one row per
     location-year-powertrain (Master_Cars_Tech), one row per location-year-mode (Master_All_Modes),
     and the 2035 scenarios (Master_Projection)
  6. derived fields: EVs per charger, entity type, global and regional market share

Writes data/rebuilt/EV_data_cleaned.xlsx and data/rebuilt/EV_master_analytical.xlsx and checks them
against the files the dashboards were built from (data/processed/).

Not rebuilt here: population, momentum and infrastructure-readiness fields, which were added to the
team's Master_Analytical sheet in Excel (they are read from data/processed/ by src/analysis.py).
"""
from __future__ import annotations

from functools import reduce
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "iea_global_ev_data_explorer_2026.xlsx"
PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "data" / "rebuilt"

COUNTRY_NAME_MAP = {"USA": "United States", "Viet Nam": "Vietnam", "Lao PDR": "Laos",
                    "Turkiye": "Turkey", "Korea": "South Korea"}

REGION_MAP = {
    **dict.fromkeys(["Chile", "Brazil", "Colombia", "Argentina", "Uruguay", "Mexico", "Costa Rica"], "Latin America"),
    **dict.fromkeys(["Norway", "Portugal", "France", "Germany", "Italy", "Netherlands", "Switzerland", "Belgium",
                     "Denmark", "Finland", "Spain", "United Kingdom", "Greece", "Iceland", "Poland", "Sweden",
                     "Austria", "Romania", "Czech Republic", "Estonia", "Hungary", "Ireland", "Latvia", "Lithuania",
                     "Luxembourg", "Slovakia", "Slovenia", "Croatia", "Cyprus", "Bulgaria"], "Europe"),
    **dict.fromkeys(["Australia", "New Zealand", "Nepal", "Uzbekistan"], "Asia Pacific"),
    "Canada": "Advanced Economies",
    **dict.fromkeys(["Cambodia", "Philippines", "Singapore", "Thailand", "Indonesia", "Malaysia", "Vietnam", "Laos"],
                    "Southeast Asia"),
    **dict.fromkeys(["South Africa", "Seychelles"], "Africa"),
    **dict.fromkeys(["Jordan", "United Arab Emirates", "Turkey", "Russia", "Israel"], "Middle East and Caspian"),
}
BIG_MARKETS = ["China", "India", "Japan", "South Korea", "United States"]       # IEA lists these as aggregates
REGION_ROLLUPS = ["Advanced Economies", "Africa", "Asia Pacific", "Developing Economies excl. China", "Europe",
                  "European Union", "Latin America", "Middle East and Caspian", "Southeast Asia"]
PIVOT_INDEX = ["Aggregate_group", "Geo_type", "Region_Country", "Region", "Category", "Year"]


def check(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def clean(raw: pd.DataFrame, geo: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    print(f"raw: {df.shape[0]:,} rows x {df.shape[1]} columns")
    price = df["parameter"].str.startswith("price_")
    check(df.loc[df["unit"].isna(), "parameter"].str.startswith("price_").all(), "missing units are price rows only")
    df.loc[price, "unit"] = "2025 USD"
    check(df.loc[df["region_country"].isna(), "parameter"].str.startswith("price_").all(),
          "missing geographies are price rows only")
    df.loc[price & df["region_country"].isna(), "region_country"] = "Unattributed"

    key = ["region_country", "category", "parameter", "mode", "powertrain", "year"]
    check((df.groupby(key)["value"].nunique() <= 1).all(), "no key has conflicting values")
    n_dup = int(df.duplicated().sum())
    df = df.drop_duplicates(keep="first").reset_index(drop=True)
    print(f"  dropped {n_dup} exact duplicate rows -> {len(df):,} rows")

    aggregates = set(geo["region_country"].replace(COUNTRY_NAME_MAP))
    df["region_country"] = df["region_country"].str.strip().replace(COUNTRY_NAME_MAP)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["Geo_type"] = np.where(df["region_country"].isin(aggregates), "aggregate", "country")
    is_agg, is_unatt = df["Geo_type"].eq("aggregate"), df["region_country"].eq("Unattributed")
    df["Region"] = np.where(is_agg, df["region_country"],
                            np.where(is_unatt, "Unattributed", df["region_country"].map(REGION_MAP)))
    df["Country"] = df["region_country"].where(~(is_agg | is_unatt))
    unmapped = df.loc[df["Geo_type"].eq("country") & ~is_unatt & df["Region"].isna(), "region_country"].unique()
    check(len(unmapped) == 0, "every country is mapped to a region")
    df = df.rename(columns={"region_country": "Region_Country", "category": "Category", "parameter": "Parameter",
                            "powertrain": "Powertrain", "mode": "Mode", "value": "Value", "year": "Year",
                            "unit": "Unit", "Aggregate group": "Aggregate_group"})
    return df[["Aggregate_group", "Geo_type", "Region_Country", "Region", "Country", "Category", "Parameter",
               "Powertrain", "Mode", "Value", "Unit", "Year"]]


def charging_with_gaps(df: pd.DataFrame) -> pd.DataFrame:
    cp = df[(df.Parameter == "EV charging points") & (df.Category == "Historical") & (df.Geo_type == "country")]
    rows = []
    for (country, pt), g in cp.groupby(["Country", "Powertrain"]):
        t = g.iloc[0]
        for yr in sorted(set(range(int(g.Year.min()), int(g.Year.max()) + 1)) - set(g.Year)):
            rows.append({**t.to_dict(), "Value": np.nan, "Year": yr})
    out = pd.concat([cp, pd.DataFrame(rows)], ignore_index=True).sort_values(["Country", "Powertrain", "Year"])
    print(f"  charging points: {len(cp)} country rows, {len(rows)} internal gap years added")
    return out.reset_index(drop=True)


def pivot(df, param, mode, powertrains, names):
    sub = df[(df.Parameter == param) & (df.Mode == mode) & df.Powertrain.isin(powertrains)]
    p = sub.pivot_table(index=PIVOT_INDEX, columns="Powertrain", values="Value", aggfunc="sum").reset_index()
    p.columns.name = None
    return p.rename(columns=names)


def classify(r) -> str:
    if r.Region_Country == "World":
        return "world"
    if r.Region_Country in REGION_ROLLUPS:
        return "region_rollup"
    return "country" if (r.Geo_type == "country" or r.Region_Country in BIG_MARKETS) else "other"


def reshape(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    hist, proj = df[df.Category == "Historical"], df[df.Category != "Historical"]
    pt = ["EV", "BEV", "PHEV", "FCEV"]
    sales = pivot(hist, "EV sales", "Cars", pt, {p: f"EV_Sales_Cars_{'Total' if p == 'EV' else p}" for p in pt})
    stock = pivot(hist, "EV stock", "Cars", pt, {p: f"EV_Stock_Cars_{'Total' if p == 'EV' else p}" for p in pt})
    share = lambda p, n: hist[(hist.Parameter == p) & (hist.Mode == "Cars") & (hist.Powertrain == "EV")][
        PIVOT_INDEX + ["Value"]].rename(columns={"Value": n})
    chg = pivot(hist, "EV charging points", "EVSE",
                ["Publicly available fast", "Publicly available slow", "Publicly available ultra-fast"],
                {"Publicly available fast": "Charging_Fast", "Publicly available slow": "Charging_Slow",
                 "Publicly available ultra-fast": "Charging_UltraFast"})
    chg["Charging_Total"] = chg[["Charging_Fast", "Charging_Slow", "Charging_UltraFast"]].sum(axis=1, min_count=1)
    m = reduce(lambda a, b: a.merge(b, on=PIVOT_INDEX, how="outer"),
               [sales, stock, share("EV sales share", "EV_Sales_Share_Cars"),
                share("EV stock share", "EV_Stock_Share_Cars"), chg])
    m["Country"] = m["Region_Country"].where(m["Geo_type"] != "aggregate")
    ok = (m.Charging_Total > 0) & m.EV_Stock_Cars_Total.notna()
    m["EVs_per_Charger"] = np.where(ok, m.EV_Stock_Cars_Total / m.Charging_Total, np.nan)
    m = m.sort_values(["Region_Country", "Category", "Year"]).reset_index(drop=True)
    check(not m.duplicated(["Region_Country", "Category", "Year"]).any(), "one row per location-year")

    # entity type and market shares (share of the world total / of the region's countries)
    m["Entity_Type"] = m.apply(classify, axis=1)
    countries = m[m.Entity_Type == "country"]
    world = m[m.Entity_Type == "world"].set_index("Year")
    m["Global_Sales_Share_Pct"] = np.where(m.Entity_Type == "country",
                                           m.EV_Sales_Cars_Total / m.Year.map(world.EV_Sales_Cars_Total) * 100, np.nan)
    m["Global_Stock_Share_Pct"] = np.where(m.Entity_Type == "country",
                                           m.EV_Stock_Cars_Total / m.Year.map(world.EV_Stock_Cars_Total) * 100, np.nan)
    reg = countries.groupby(["Region", "Year"])[["EV_Sales_Cars_Total", "EV_Stock_Cars_Total"]].sum()
    key = list(zip(m.Region, m.Year))
    m["Regional_Sales_Share_Pct"] = np.where(
        m.Entity_Type == "country", m.EV_Sales_Cars_Total / reg.EV_Sales_Cars_Total.reindex(key).to_numpy() * 100, np.nan)
    m["Regional_Stock_Share_Pct"] = np.where(
        m.Entity_Type == "country", m.EV_Stock_Cars_Total / reg.EV_Stock_Cars_Total.reindex(key).to_numpy() * 100, np.nan)

    tech_idx = PIVOT_INDEX + ["Powertrain"]
    b_s = hist[(hist.Parameter == "EV sales") & (hist.Mode == "Cars") & hist.Powertrain.isin(pt[1:])][
        tech_idx + ["Value"]].rename(columns={"Value": "EV_Sales_Cars"})
    b_k = hist[(hist.Parameter == "EV stock") & (hist.Mode == "Cars") & hist.Powertrain.isin(pt[1:])][
        tech_idx + ["Value"]].rename(columns={"Value": "EV_Stock_Cars"})
    cars_tech = b_s.merge(b_k, on=tech_idx, how="outer").sort_values(
        ["Region_Country", "Category", "Year", "Powertrain"]).reset_index(drop=True)
    mode_idx = PIVOT_INDEX + ["Mode"]
    c_s = hist[(hist.Parameter == "EV sales") & (hist.Powertrain == "EV")][mode_idx + ["Value"]].rename(
        columns={"Value": "EV_Sales_Total"})
    c_k = hist[(hist.Parameter == "EV stock") & (hist.Powertrain == "EV")][mode_idx + ["Value"]].rename(
        columns={"Value": "EV_Stock_Total"})
    modes = c_s.merge(c_k, on=mode_idx, how="outer").sort_values(
        ["Region_Country", "Category", "Year", "Mode"]).reset_index(drop=True)
    return {"Master_Analytical": m, "Master_Cars_Tech": cars_tech, "Master_All_Modes": modes,
            "Master_Projection": proj.reset_index(drop=True)}


def compare_with_team(sheets: dict[str, pd.DataFrame]):
    """The rebuilt tables must match the team's files the dashboards were built on."""
    team = pd.read_excel(PROCESSED / "EV_master_analytical.xlsx", sheet_name=None)
    for name in ["Master_Analytical", "Master_Cars_Tech", "Master_All_Modes", "Master_Projection"]:
        a, b = sheets[name], team[name]
        cols = [c for c in b.columns if c in a.columns and pd.api.types.is_numeric_dtype(b[c]) and c != "Year"]
        key = [c for c in ["Region_Country", "Category", "Year", "Powertrain", "Mode", "Parameter"]
               if c in a.columns and c in b.columns]
        j = a.merge(b, on=key, suffixes=("", "_team"), how="outer", indicator=True)
        num = lambda x: pd.to_numeric(x, errors="coerce").astype(float)
        if name == "Master_Analytical":                       # the team named the share columns My_*
            for c in ["Global_Sales_Share_Pct", "Global_Stock_Share_Pct",
                      "Regional_Sales_Share_Pct", "Regional_Stock_Share_Pct"]:
                j[f"{c}_team"] = j[f"My_{c}"]
                cols = cols + [c]
        mism = sum(int((~np.isclose(num(j[c]), num(j[f"{c}_team"]), equal_nan=True)).sum()) for c in cols)
        check(len(a) == len(b) and (j["_merge"] == "both").all() and mism == 0,
              f"{name}: {len(a):,} rows, {len(cols)} numeric columns identical to the team's file")


def main():
    raw = pd.read_excel(RAW, sheet_name="GEVO_EV_2026")
    geo = pd.read_excel(RAW, sheet_name="Regions and countries")
    df = clean(raw, geo)
    OUT.mkdir(parents=True, exist_ok=True)
    cp = charging_with_gaps(df)
    with pd.ExcelWriter(OUT / "EV_data_cleaned.xlsx") as w:
        df.to_excel(w, sheet_name="Master", index=False)
        cp.to_excel(w, sheet_name="Charging_Points", index=False)
    sheets = reshape(df)
    with pd.ExcelWriter(OUT / "EV_master_analytical.xlsx") as w:
        for k, v in sheets.items():
            v.to_excel(w, sheet_name=k, index=False)
    for k, v in sheets.items():
        print(f"  {k}: {v.shape[0]:,} rows x {v.shape[1]} columns")
    compare_with_team(sheets)
    print(f"written to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
