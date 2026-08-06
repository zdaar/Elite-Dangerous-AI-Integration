---
name: elite-station-services
description: Verified Elite Dangerous station-service facts and strict routing rules for selling exploration data, exobiology samples, and locating service combinations.
---

# Station services and data sales

## Sale destinations

- **Universal Cartographics** is the station service used to sell exploration and cartographic scan data.
- **Vista Genomics** is the station service used to sell completed genetic samples collected with the Artemis genetic sampler.
- These services are independent. A commander carrying both exploration data and genetic samples needs a station whose live service list contains **both** `Universal Cartographics` and `Vista Genomics` to sell everything at one stop.
- A station being populated, dockable, High Tech, scientific, or inside the Bubble does not prove either service is installed. Only the station's explicit service list is sufficient evidence.

## Destination-search contract

Use the Spansh station search with one combined-filter entry per required service. Multiple service entries form an intersection. After the response, independently reject every row whose returned `services` array does not contain every requested service.

Do not recommend or navigate to a partial match. If no exact match is returned, say that the exact search failed and broaden its radius or change only a commander-approved constraint. Never substitute a nearby generic station.

Player fleet carriers can move and may restrict docking. Exclude them by default for a dependable destination; include them only when the commander accepts that uncertainty.

If the commander reports that a station or permit system is inaccessible, exclude that exact station/system and repeat the same service-constrained search. Do not reuse it as a recommendation.

## Evidence

- Spansh live station schema: `services` is a repeatable `combined` field with a `name` group. Its live vocabulary includes `Universal Cartographics` and `Vista Genomics`.
- Frontier's System Colonisation service matrix lists Universal Cartographics and Vista Genomics as separate port services with different installation requirements: https://www.elitedangerous.com/fr-FR/actualit%C3%A9s?page=4
- Frontier journal sale events distinguish `MultiSellExplorationData`/`SellExplorationData` from `SellOrganicData`, which is the authoritative live confirmation of the corresponding sale.
