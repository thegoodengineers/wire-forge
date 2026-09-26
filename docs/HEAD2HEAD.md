# Head-to-head

Generated from `bench/head2head/*.json` by `python -m wireforge.scorecard`. Do not edit by hand.

## boat-lifestyle.com

Goal: add a product in a given colour variant and quantity to the cart, then return the cart contents

| system | time to ship | action type | cost / call | verification | failure transparency |
|---|---|---|---|---|---|
| anakin-build-request | 5m 14s | native-endpoint | 25 credits to build, 1 credit per call | builder's internal auto-test (not visible); our run via POST /v1/wire/task completed in 9.8 s, item added | none |
| wire-forge | 3m 18s | native-endpoint | no Anakin credits | independent verifier: 7/7 values matched the live cart; write stored on the site | none |
| wire-from-forge-spec | 4m 41s | native-endpoint | 25 credits to build, 1 credit per call | ran via POST /v1/wire/task with product/colour/quantity: completed in 12.6 s, item added | none |

## myntra.com

Goal: search products by keyword with brand and price filters, paginated

| system | time to ship | action type | cost / call | verification | failure transparency |
|---|---|---|---|---|---|
| anakin-build-request | 6m 25s | native-endpoint | 25 credits to build, 1 credit per call | builder's internal auto-test (not visible); our run via POST /v1/wire/task completed in 6.3 s and returned 177 Nike sneakers | none |
| wire-forge | 3m 39s | native-endpoint | no Anakin credits | independent verifier: 6/6 values matched Myntra's own backend (the verifier's browser could not load the pages) | none |
