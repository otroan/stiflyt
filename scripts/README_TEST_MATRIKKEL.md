# Matrikkel Integration Test Script

## Overview

The `test_matrikkel_integration.py` script verifies that the Matrikkel API integration:
1. **Deduplicates matrikkelenheter** before making API calls
2. **Uses bulk operations** instead of individual API calls
3. **Correctly maps results** back to all original items

## Running the Test

### Basic Usage

```bash
# Test with default route (bre10)
python scripts/test_matrikkel_integration.py

# Test with a specific route
python scripts/test_matrikkel_integration.py bre5
```

### Prerequisites

1. **Database access**: For testing with real routes, the database must be accessible
2. **Matrikkel credentials** (optional): Set environment variables for real API testing:
   ```bash
   export MATRIKKEL_USERNAME=your_username
   export MATRIKKEL_PASSWORD=your_password
   ```

   Without credentials, the test will still run but will show warnings and use mock data.

## What the Test Verifies

### 1. Deduplication Analysis

The test analyzes test data to identify:
- Total number of matrikkelenhet items
- Number of unique matrikkelenheter
- Number of duplicate entries
- Efficiency metrics

**Example Output:**
```
Test Data Analysis:
  Total items: 6
  Unique matrikkelenheter: 3
  Duplicate entries: 3

  Duplicates found:
    (1234, 56, 78, None): 3 occurrences
    (5678, 90, 12, 34): 2 occurrences
```

### 2. Bulk Operation Verification

The test verifies that:
- API calls are made in batches, not one-by-one
- The number of API calls matches the number of unique matrikkelenheter
- Results are correctly mapped back to all original items

### 3. Real Route Testing

When testing with a real route, the script:
- Fetches route data from the database
- Analyzes uniqueness in the route's matrikkelenhet_vector
- Fetches owner information (if credentials are available)
- Reports performance metrics

## Improvements Made

### Before (Original Implementation)

The service processed all items sequentially, making API calls for duplicates:
- **Problem**: If a route has 100 items but only 50 unique matrikkelenheter, it would make 100 API calls
- **Efficiency**: 50% (wasting 50 API calls)

### After (Improved Implementation)

The service now:
1. **Deduplicates** matrikkelenheter before API calls
2. **Makes bulk API calls** only for unique matrikkelenheter
3. **Maps results back** to all original items

**Benefits**:
- Reduces API calls from N to M (where M = unique matrikkelenheter)
- Improves performance
- Reduces API rate limit issues
- Maintains correct mapping to all original items

## Test Output Example

```
================================================================================
MATRIKKEL INTEGRATION TEST SUITE
================================================================================

================================================================================
TEST: Deduplication and Bulk Operations
================================================================================

Test Data Analysis:
  Total items: 6
  Unique matrikkelenheter: 3
  Duplicate entries: 3

  Duplicates found:
    (1234, 56, 78, None): 3 occurrences
    (5678, 90, 12, 34): 2 occurrences

  Results: 6 items processed in 0.123s
  All items returned: True
  All original items present in results: True

================================================================================
TEST: Deduplication Logic
================================================================================

  Test data has 6 items
  But only 3 unique matrikkelenheter

  Current Implementation Analysis:
    The service processes all items, which means:
    - API calls for duplicates: 3 unnecessary calls
    - Efficiency: 50.0%

  Recommendation:
    The service should deduplicate matrikkelenheter before API calls,
    then map results back to all original items.
    This would reduce API calls from 6 to 3

================================================================================
TEST: Real Route Data (bre10)
================================================================================

  Fetching route data for 'bre10'...
  Found 45 matrikkelenhet items

  Uniqueness Analysis:
    Total items: 45
    Unique matrikkelenheter: 32
    Duplicate entries: 13

    ⚠️  WARNING: 13 duplicate entries found!
       This means the same matrikkelenhet appears multiple times.
       The service should deduplicate before API calls for efficiency.
       Potential efficiency loss: 28.9%

  Fetching owner information for 45 items...
  Results:
    Time elapsed: 2.456s
    Average per item: 54.58ms
    Average per unique matrikkelenhet: 76.75ms

  Owner Information:
    Successful: 28
    Failed: 2
    Empty (no owners): 2
```

## Key Metrics

The test reports:
- **Total items**: Number of matrikkelenhet items in the route
- **Unique matrikkelenheter**: Number of distinct matrikkelenheter
- **Duplicate entries**: Number of duplicate occurrences
- **Efficiency**: Percentage of unique matrikkelenheter
- **API call reduction**: How many calls were saved by deduplication
- **Performance**: Time per item and per unique matrikkelenhet

## Troubleshooting

### "Matrikkel credentials not configured"

This is expected if you haven't set up API credentials. The test will still run and analyze deduplication, but won't fetch real owner information.

### "Could not test with real route"

This means the database connection failed. Check:
- Database is running
- Connection settings are correct
- Route identifier exists

### "No matrikkelenheter found"

The route doesn't have any matrikkelenhet intersections. This is normal for some routes.

## Next Steps

After running the test:
1. Review the deduplication metrics
2. Verify that API calls match unique matrikkelenheter (not total items)
3. Check performance metrics
4. Ensure all items get owner information mapped correctly
