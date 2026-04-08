# Unmapped Traits: Quick Wins Analysis

**TL;DR:** Add 2 simple functions to map **170,626 observations** (70% of all unmapped data)

---

## The Opportunity

**Current unmapped:** 244,534 observations  
**Can be mapped with 2 functions:** 170,626 observations (69.8%)  
**Effort:** 2-3 hours  
**Complexity:** LOW

---

## Problem

Three patterns account for 99.4% of unmapped observations:

```
growth: 42 degrees Celsius     → 85,313 observations (UNMAPPED)
growth: 6.5% NaCl               → 85,313 observations (UNMAPPED)
cell color: yellow pigment      → 73,391 observations (intentionally skipped)
```

### Why They're Unmapped

1. **Temperature/NaCl observations:** No handler exists for specific point observations
   - METPO predicates exist: METPO:2000054, METPO:2000508
   - Code only handles optimum/range values from numerical data
   - These are boolean observations from MetaTraits: "Can organism X grow at 42°C?"

2. **Yellow pigment:** Negative assertions intentionally skipped
   - METPO class exists: METPO:1003030
   - These are "does NOT have yellow pigment" observations
   - Current design decision: negative assertions add limited value

---

## Solution: Add 2 Handler Functions

### Function 1: Growth Temperature Observations

**Add to `metatraits.py`:**

```python
def _resolve_growth_temperature_observation(
    self, trait_name: str, majority_label: str
) -> Optional[dict]:
    """
    Resolve specific growth temperature observations.
    
    Handles patterns like:
    - "growth: 42 degrees Celsius" (true/false)
    - "growth: 37 degrees celsius" (true/false)
    
    Uses METPO:2000054 (has growth temperature observation) as predicate
    and creates a quantitative edge with the temperature value.
    
    :param trait_name: The trait name to resolve
    :param majority_label: The majority boolean value (e.g., "true: (92%)")
    :return: dict with observation details or None if no match
    """
    import re
    
    # Pattern: growth: <number> degrees Celsius/celsius
    match = re.match(
        r"^growth:\s*(\d+(?:\.\d+)?)\s*degrees?\s*celsius$",
        trait_name.lower()
    )
    if not match:
        return None
    
    temp_value = float(match.group(1))
    can_grow = "true" in majority_label.lower()
    
    # Use METPO observation predicate
    predicate = "METPO:2000054"  # has growth temperature observation
    
    # Note: This creates a quantitative observation edge
    # The boolean value (can_grow) should be encoded as a qualifier or
    # separate field in the edge. For now, we can use the predicate itself
    # to indicate the observation was made, and store the value.
    
    return {
        "observation_type": "temperature",
        "predicate": predicate,
        "value": temp_value,
        "unit": "Cel",  # UCUM code for Celsius
        "can_grow": can_grow,
        "biolink_predicate": "biolink:has_attribute",
    }
```

### Function 2: Growth NaCl Observations

**Add to `metatraits.py`:**

```python
def _resolve_growth_nacl_observation(
    self, trait_name: str, majority_label: str
) -> Optional[dict]:
    """
    Resolve specific growth NaCl/salinity observations.
    
    Handles patterns like:
    - "growth: 6.5% NaCl" (true/false)
    - "growth: 10% NaCl" (true/false)
    - "growth: 1% sodium chloride" (true/false)
    
    Uses METPO:2000508 (has growth NaCl observation) as predicate
    and creates a quantitative edge with the NaCl concentration.
    
    :param trait_name: The trait name to resolve
    :param majority_label: The majority boolean value
    :return: dict with observation details or None if no match
    """
    import re
    
    # Pattern 1: growth: <number>% NaCl
    match = re.match(
        r"^growth:\s*(\d+(?:\.\d+)?)\s*%\s*nacl$",
        trait_name.lower()
    )
    
    # Pattern 2: growth: <number>% sodium chloride
    if not match:
        match = re.match(
            r"^growth:\s*(\d+(?:\.\d+)?)\s*%\s*sodium\s+chloride$",
            trait_name.lower()
        )
    
    if not match:
        return None
    
    nacl_percent = float(match.group(1))
    can_grow = "true" in majority_label.lower()
    
    # Use METPO observation predicate
    predicate = "METPO:2000508"  # has growth NaCl observation
    
    return {
        "observation_type": "nacl",
        "predicate": predicate,
        "value": nacl_percent,
        "unit": "%",
        "can_grow": can_grow,
        "biolink_predicate": "biolink:has_attribute",
    }
```

---

## Integration into Dispatch Chain

**Add to trait resolution logic (around line 2573):**

```python
# Tier 3.0a: Growth temperature observations
elif temp_obs := self._resolve_growth_temperature_observation(
    trait_name, majority_label
):
    # Create observation node or edge
    # Option 1: Create as quantitative attribute edge
    edges.append({
        "subject": taxon_curie,
        "predicate": self.METPO_TO_BIOLINK_PREDICATE.get(
            temp_obs["predicate"], 
            "biolink:has_attribute"
        ),
        "object": f"kgmicrobe.observation:{taxon_curie}_{trait_name}",
        "relation": temp_obs["predicate"],
        "has_value": temp_obs["value"],
        "has_unit": temp_obs["unit"],
        "growth_result": "positive" if temp_obs["can_grow"] else "negative",
    })
    mapped_count += 1

# Tier 3.0b: Growth NaCl observations
elif nacl_obs := self._resolve_growth_nacl_observation(
    trait_name, majority_label
):
    # Create observation node or edge
    edges.append({
        "subject": taxon_curie,
        "predicate": self.METPO_TO_BIOLINK_PREDICATE.get(
            nacl_obs["predicate"],
            "biolink:has_attribute"
        ),
        "object": f"kgmicrobe.observation:{taxon_curie}_{trait_name}",
        "relation": nacl_obs["predicate"],
        "has_value": nacl_obs["value"],
        "has_unit": nacl_obs["unit"],
        "growth_result": "positive" if nacl_obs["can_grow"] else "negative",
    })
    mapped_count += 1
```

---

## Alternative: Simpler Approach (Just Skip Them)

If modeling quantitative observations with boolean results is too complex for now, we can simply track these as "known but intentionally not modeled":

```python
# Tier 3.0a: Growth temperature observations (track but don't model yet)
elif re.match(r"^growth:\s*\d+(?:\.\d+)?\s*degrees?\s*celsius$", trait_name.lower()):
    # Known pattern - specific temperature test observations
    # Not modeled yet (requires quantitative observation framework)
    continue

# Tier 3.0b: Growth NaCl observations (track but don't model yet)
elif re.match(r"^growth:\s*\d+(?:\.\d+)?\s*%\s*nacl$", trait_name.lower()):
    # Known pattern - specific NaCl test observations
    # Not modeled yet (requires quantitative observation framework)
    continue
```

This would move them from "unmapped" to "known but deferred", improving reporting clarity.

---

## Additional Quick Wins

### Fix pH Preference Handler (33 observations)

**Issue:** Handler exists but not catching "pH preference" observations

**Debug:**
```python
# Around line 1813 in _resolve_ph_preference_trait()
def _resolve_ph_preference_trait(self, trait_name: str, majority_label: str) -> Optional[dict]:
    """Resolve pH preference categorical traits."""
    
    # ADD LOGGING
    if trait_name.lower() == "ph preference":
        print(f"DEBUG: pH preference found - majority_label='{majority_label}'")
    
    # Check if majority_label is empty/malformed
    if not majority_label or majority_label == "No robust majority":
        return None
    
    # ... rest of function
```

---

## Expected Impact

| Implementation | Observations Mapped | Effort | Complexity |
|----------------|---------------------|--------|------------|
| **Full implementation** (create observation edges) | **170,626** | 4-6 hours | MEDIUM |
| **Simple skip** (just don't report as unmapped) | **170,626** | 30 min | LOW |
| **pH preference fix** | 33 | 30 min | LOW |

---

## Decision Required

**Question:** How should boolean growth observations be modeled?

**Option A:** Create quantitative observation edges
- More semantically rich
- Captures: temperature value, unit, growth result (positive/negative)
- Complexity: MEDIUM
- Example: `NCBITaxon:X -[METPO:2000054]-> Observation:X_42C {value: 42, unit: Cel, result: positive}`

**Option B:** Skip for now, track as "deferred"
- Simple and fast
- Moves from "unmapped" to "known pattern - deferred"
- Can implement proper modeling later
- Complexity: LOW

**Option C:** Model as simple binary edges
- Create specific METPO class nodes for each test condition
- Example: `METPO:growth_42C_positive`
- Requires many custom terms
- Complexity: MEDIUM-HIGH
- Not recommended (not ontologically sound)

---

## Recommendation

**Phase 1 (Now):** Option B - Track as known/deferred patterns  
**Phase 2 (Later):** Option A - Implement full quantitative observation framework

This provides immediate clarity in unmapped reporting while leaving room for proper modeling in future work.
