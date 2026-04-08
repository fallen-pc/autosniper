# DEC-002: curves govern resale estimates

Status: accepted
Date: 2026-04-08

## Decision
Resale estimates are governed by curves rather than directly by sold-car history.

## Reason
Curves are the controlled valuation surface for consistent resale guidance. Letting ad hoc sold-car history override them would blur valuation rules and make outputs harder to trust.

## Consequences
Valuation tasks must load curve contracts and this decision before changing resale logic.
