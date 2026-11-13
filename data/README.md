# Data

## Source
International Energy Agency (2026), *Global EV Outlook 2026*, Global EV Data Explorer.
https://www.iea.org/data-and-statistics/data-tools/global-ev-data-explorer

Licence: Creative Commons Attribution 4.0 (CC BY 4.0). The file is redistributed unchanged except for its name.

## Files
| File | Rows | Contents |
|---|---|---|
| `raw/iea_global_ev_data_explorer_2026.xlsx` | 49,176 | IEA long-format table (sheet `GEVO_EV_2026`): region_country, category (Historical, Projection-CPS, Projection-STEPS), parameter, mode, powertrain, year, unit, value; plus the IEA's notes, definitions and region list |
| `processed/EV_data_cleaned.xlsx` | 49,161 | cleaned long table (`Master`) and country charging points with internal gaps marked (`Charging_Points`, 924 rows) |
| `processed/EV_master_analytical.xlsx` | | the Tableau data source: `Master_Analytical` (928 market-years), `Master_Cars_Tech` (2,119), `Master_All_Modes` (2,887), `Master_Projection` (1,261), `World_Trajectory` (20) |
| `rebuilt/` | | written by `src/build_dataset.py` (not committed) |

## Key fields in `Master_Analytical`
| Field | Meaning |
|---|---|
| `Region_Country`, `Geo_type`, `Region`, `Entity_Type` | market name; country or IEA aggregate; IEA region; country / region_rollup / world |
| `EV_Sales_Cars_*`, `EV_Stock_Cars_*` | EV car sales and stock: Total, BEV, PHEV, FCEV |
| `EV_Sales_Share_Cars`, `EV_Stock_Share_Cars` | EV share of new car sales / of the car fleet (%) |
| `Charging_Fast/Slow/UltraFast/Total` | publicly available charging points |
| `EVs_per_Charger` | EV car stock / public charging points |
| `My_Global_*_Share_Pct`, `My_Regional_*_Share_Pct` | market's share of world / regional EV car sales and stock |
| `YoY_Growth`, `Momentum_3yr_Growth_Pct`, `YoY_Momentum` | growth metrics (added in Excel) |
| `Population`, `IR 1`, `IR 2`, `Infrastructure Readiness` | population and readiness tiers (chargers per EV, chargers per 100k people; added in Excel) |

## Definitions (IEA)
- **EV sales**: new vehicle registrations where available, otherwise retail sales.
- **EV stock**: vehicles on the road.
- **BEV** battery electric, **PHEV** plug-in hybrid, **FCEV** hydrogen fuel cell.
- **CPS / STEPS**: Current Policies Scenario / Stated Policies Scenario for 2035.
- All values are rounded to two significant figures by the IEA.
