# Stiflyt Route Query CLI

Command-line interface for querying route segments from the Stiflyt backend API.

## Installation

The CLI is installed automatically when you install the stiflyt package:

```bash
pip install -e .
```

## Usage

### Basic Query

Query segments with rutenummer starting with "bre" and vedlikeholdsansvarlig "DNT Oslo":

```bash
query-routes --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo"
```

### Output Formats

**Table format (default):**
```bash
query-routes --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo"
```

**JSON format:**
```bash
query-routes --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo" --format json
```

**CSV format:**
```bash
query-routes --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo" --format csv --output results.csv
```

### Options

- `--rutenummer-prefix TEXT`: Filter by route number prefix (e.g., "bre")
- `--vedlikeholdsansvarlig TEXT`: Filter by organization (e.g., "DNT Oslo")
- `--format [json|table|csv]`: Output format (default: table)
- `--include-geometry`: Include GeoJSON geometry in response (only for JSON format)
- `--output FILE`: Write output to file instead of stdout
- `--limit INTEGER`: Maximum number of results (default: 100, max: 1000)
- `--offset INTEGER`: Offset for pagination (default: 0)
- `--api-url TEXT`: API base URL (default: http://localhost:8000/api/v1)
- `--username TEXT`: HTTP Basic Auth username
- `--password TEXT`: HTTP Basic Auth password
- `--timeout INTEGER`: Request timeout in seconds (default: 30)
- `--verbose`: Show verbose error messages
- `--no-summary`: Do not show summary information (table format only)

### Environment Variables

You can configure the CLI using environment variables:

- `STIFLYT_API_URL`: API base URL (default: http://localhost:8000/api/v1)
- `STIFLYT_USERNAME`: HTTP Basic Auth username
- `STIFLYT_PASSWORD`: HTTP Basic Auth password

### Examples

**Query with just rutenummer prefix:**
```bash
query-routes --rutenummer-prefix bre
```

**Query with pagination:**
```bash
query-routes --rutenummer-prefix bre --limit 50 --offset 100
```

**Custom API URL:**
```bash
query-routes --rutenummer-prefix bre --api-url http://production.example.com/api/v1
```

**JSON output with geometry:**
```bash
query-routes --rutenummer-prefix bre --vedlikeholdsansvarlig "DNT Oslo" --format json --include-geometry
```

## Error Handling

The CLI handles various error conditions:

- **Connection errors**: When the API is unreachable
- **Authentication errors**: When credentials are invalid
- **API errors**: When the API returns an error response
- **Validation errors**: When required parameters are missing

Use `--verbose` to see detailed error messages.

