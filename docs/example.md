# Worked example

This is the exact output for the sample files in `data/`. A test fails if it goes out of date.

```text
# Dosewise report

9 findings. 1 need action. 4 score exactly zero.
By band: Act 1, Monitor 3, No Action 5.
Action line (from the written reference case): 1.50

| rank | was (by downstream count) | asset | change | risk | band |
|---|---|---|---|---|---|
| 1 | 3 | warehouse.customers | column_removed | 1.55 | Act |
| 2 | 5 | warehouse.web_events | type_changed | 1.24 | Monitor |
| 3 | 2 | warehouse.addresses | column_removed | 0.8 | Monitor |
| 4 | 4 | warehouse.orders | type_changed | 0.39 | Monitor |
| 5 | 1 | postgres.addresses | column_removed | 0.13 | No Action |
| 6 | 6 | warehouse.legacy_fx | standing:no owner | 0.0 | No Action |
| 7 | 7 | warehouse.promo_codes | standing:mixed case names | 0.0 | No Action |
| 8 | 8 | warehouse.promo_codes | standing:no description | 0.0 | No Action |
| 9 | 9 | warehouse.sessions | standing:nullable key | 0.0 | No Action |

## Why

**warehouse.customers** (column_removed, Act): column removed on 2 of 9 columns (22%); 1 downstream, 3000 weighted queries a month after distance decay; most sensitive consumer weighs 2.0x.
  Hazard 1.0 x dose 0.2222 x exposure 3.477 x receptor 2.0 x uncertainty 1.0 = 1.55

**warehouse.web_events** (type_changed, Monitor): type changed on 1 of 9 columns (11%); nobody owns this table, so nobody is accountable: missing evidence raises uncertainty; 1 downstream, 3000 weighted queries a month after distance decay; most sensitive consumer weighs 2.0x; would move to Act if the risk were 1.2x higher; filling in the missing evidence could move this up or down.
  Hazard 0.8 x dose 0.1111 x exposure 3.477 x receptor 2.0 x uncertainty 2.0 = 1.24

**warehouse.addresses** (column_removed, Monitor): column removed on 2 of 9 columns (22%); 1 downstream, 600 weighted queries a month after distance decay; most sensitive consumer weighs 1.3x; would move to Act if the risk were 1.9x higher.
  Hazard 1.0 x dose 0.2222 x exposure 2.779 x receptor 1.3 x uncertainty 1.0 = 0.8

**warehouse.orders** (type_changed, Monitor): type changed on 1 of 9 columns (11%); 1 downstream, 900 weighted queries a month after distance decay; most sensitive consumer weighs 1.5x; would move to Act if the risk were 3.8x higher.
  Hazard 0.8 x dose 0.1111 x exposure 2.955 x receptor 1.5 x uncertainty 1.0 = 0.39

**postgres.addresses** (column_removed, No Action): column removed on 2 of 9 columns (22%); 4 downstream, 0 weighted queries a month after distance decay; 4 consumer(s) have no usage data, which raises uncertainty rather than lowering risk; would move to Monitor if the risk were 2.8x higher; filling in the missing evidence could move this up or down.
  Hazard 1.0 x dose 0.2222 x exposure 0.3 x receptor 1.0 x uncertainty 2.0 = 0.13

## Risk by domain

- (no domain): 2.17
- customer: 1.55
- finance: 0.39

## Scored zero

These are real, but nothing about them changed, so they are not today's problem:

- warehouse.legacy_fx: no owner
- warehouse.promo_codes: mixed case names
- warehouse.promo_codes: no description
- warehouse.sessions: nullable key
```
