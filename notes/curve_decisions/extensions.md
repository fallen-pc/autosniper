# Curve Extension Decisions

## Standard Same-Lane High-Km Extensions

Current working interpretation:
- high-km extension buckets are `225000` and `300000`
- extensions are allowed only when the vehicle lane is unchanged: same generation, body, drivetrain, transmission, and material trim lane
- extensions follow the existing curve shape for that lane
- new body, drivetrain, generation, or materially different badge lanes require new Carsales/private retail evidence instead of extrapolating from a neighbouring curve

Implementation note:
- The 2026-06-02 extension pass added missing `225000` and `300000` rows to existing curves using lane-level depreciation from the existing `150000` to `200000` curve shape.
- Existing Carsales-led extension rows were preserved.
- Retail curves must not be sanity checked or repriced against Grays sold prices. Grays sold history remains hammer-bid evidence only.
