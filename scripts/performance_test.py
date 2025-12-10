#!/usr/bin/env python3
"""
Performance test script for Stiflyt Route API.

Tests the bounding box routes endpoint with various scenarios:
- Different bounding box sizes
- With and without filters (DNT, prefix)
- Concurrent requests
- Response time statistics

Usage:
    python scripts/performance_test.py
    python scripts/performance_test.py --url http://localhost:8000
    python scripts/performance_test.py --concurrent 10 --iterations 50
    python scripts/performance_test.py --small-only
"""

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("Error: requests library not found. Install it with: pip install requests")
    exit(1)


class PerformanceTest:
    """Performance testing class for API endpoints."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize performance test.

        Args:
            base_url: Base URL of the API server
        """
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"
        self.results: List[Dict] = []

    def test_bbox_endpoint(
        self,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        prefix: str = None,
        organization: str = None,
        limit: int = 100,
    ) -> Tuple[float, Dict]:
        """
        Test the bounding box routes endpoint.

        Returns:
            Tuple of (response_time_seconds, response_data)
        """
        params = {
            "min_lat": min_lat,
            "min_lng": min_lng,
            "max_lat": max_lat,
            "max_lng": max_lng,
            "limit": limit,
        }

        if prefix:
            params["prefix"] = prefix
        if organization:
            params["organization"] = organization

        url = f"{self.api_base}/routes/bbox?{urlencode(params)}"

        start_time = time.time()
        try:
            response = requests.get(url, timeout=30)
            elapsed = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                return elapsed, {
                    "success": True,
                    "status_code": response.status_code,
                    "response_time": elapsed,
                    "route_count": data.get("total", 0),
                    "response_size_bytes": len(response.content),
                }
            else:
                return elapsed, {
                    "success": False,
                    "status_code": response.status_code,
                    "response_time": elapsed,
                    "error": response.text[:200],
                }
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start_time
            return elapsed, {
                "success": False,
                "response_time": elapsed,
                "error": str(e),
            }

    def run_single_test(
        self,
        test_name: str,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        prefix: str = None,
        organization: str = None,
        limit: int = 100,
        iterations: int = 5,
    ) -> Dict:
        """
        Run a single test scenario multiple times and collect statistics.

        Returns:
            Dictionary with test results and statistics
        """
        print(f"\n{'='*60}")
        print(f"Test: {test_name}")
        print(f"{'='*60}")
        print(f"BBox: ({min_lat}, {min_lng}) to ({max_lat}, {max_lng})")
        if prefix:
            print(f"Prefix filter: {prefix}")
        if organization:
            print(f"Organization filter: {organization}")
        print(f"Iterations: {iterations}")
        print(f"Running...", end="", flush=True)

        response_times = []
        route_counts = []
        response_sizes = []
        errors = []

        for i in range(iterations):
            print(".", end="", flush=True)
            elapsed, result = self.test_bbox_endpoint(
                min_lat, min_lng, max_lat, max_lng, prefix, organization, limit
            )

            response_times.append(result["response_time"])

            if result["success"]:
                route_counts.append(result["route_count"])
                response_sizes.append(result["response_size_bytes"])
            else:
                errors.append(result)

        print()  # New line after dots

        if errors:
            print(f"  ⚠️  {len(errors)} errors occurred")
            for error in errors[:3]:  # Show first 3 errors
                print(f"     Error: {error.get('error', 'Unknown error')}")

        # Calculate statistics
        stats = {
            "test_name": test_name,
            "parameters": {
                "bbox": f"({min_lat}, {min_lng}) to ({max_lat}, {max_lng})",
                "prefix": prefix,
                "organization": organization,
                "limit": limit,
            },
            "iterations": iterations,
            "success_count": len(response_times) - len(errors),
            "error_count": len(errors),
            "response_times": {
                "mean": statistics.mean(response_times) if response_times else 0,
                "median": statistics.median(response_times) if response_times else 0,
                "min": min(response_times) if response_times else 0,
                "max": max(response_times) if response_times else 0,
                "stdev": statistics.stdev(response_times) if len(response_times) > 1 else 0,
            },
        }

        if route_counts:
            stats["route_counts"] = {
                "mean": statistics.mean(route_counts),
                "min": min(route_counts),
                "max": max(route_counts),
            }

        if response_sizes:
            stats["response_sizes"] = {
                "mean_bytes": statistics.mean(response_sizes),
                "mean_kb": statistics.mean(response_sizes) / 1024,
            }

        # Calculate throughput (requests per second)
        if stats["response_times"]["mean"] > 0:
            stats["throughput"] = {
                "requests_per_second": 1.0 / stats["response_times"]["mean"],
            }

        return stats

    def run_concurrent_test(
        self,
        test_name: str,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        prefix: str = None,
        organization: str = None,
        limit: int = 100,
        concurrent_requests: int = 10,
    ) -> Dict:
        """
        Run concurrent requests to test load handling.

        Returns:
            Dictionary with concurrent test results
        """
        print(f"\n{'='*60}")
        print(f"Concurrent Test: {test_name}")
        print(f"{'='*60}")
        print(f"Concurrent requests: {concurrent_requests}")
        print(f"Running...", end="", flush=True)

        response_times = []
        route_counts = []
        errors = []

        def make_request():
            elapsed, result = self.test_bbox_endpoint(
                min_lat, min_lng, max_lat, max_lng, prefix, organization, limit
            )
            return elapsed, result

        start_time = time.time()
        with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
            futures = [executor.submit(make_request) for _ in range(concurrent_requests)]

            for future in as_completed(futures):
                print(".", end="", flush=True)
                elapsed, result = future.result()
                response_times.append(result["response_time"])

                if result["success"]:
                    route_counts.append(result["route_count"])
                else:
                    errors.append(result)

        total_time = time.time() - start_time
        print()  # New line after dots

        if errors:
            print(f"  ⚠️  {len(errors)} errors occurred")

        stats = {
            "test_name": test_name,
            "concurrent_requests": concurrent_requests,
            "total_time": total_time,
            "success_count": len(response_times) - len(errors),
            "error_count": len(errors),
            "response_times": {
                "mean": statistics.mean(response_times) if response_times else 0,
                "median": statistics.median(response_times) if response_times else 0,
                "min": min(response_times) if response_times else 0,
                "max": max(response_times) if response_times else 0,
                "p95": self._percentile(response_times, 95) if response_times else 0,
                "p99": self._percentile(response_times, 99) if response_times else 0,
            },
            "throughput": {
                "requests_per_second": concurrent_requests / total_time if total_time > 0 else 0,
            },
        }

        if route_counts:
            stats["route_counts"] = {
                "mean": statistics.mean(route_counts),
            }

        return stats

    @staticmethod
    def _percentile(data: List[float], percentile: float) -> float:
        """Calculate percentile of a list."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = (percentile / 100.0) * (len(sorted_data) - 1)
        if index.is_integer():
            return sorted_data[int(index)]
        lower = sorted_data[int(index)]
        upper = sorted_data[int(index) + 1]
        return lower + (upper - lower) * (index - int(index))

    def print_summary(self, all_results: List[Dict]):
        """Print summary of all test results."""
        print(f"\n{'='*80}")
        print("PERFORMANCE TEST SUMMARY")
        print(f"{'='*80}\n")

        for result in all_results:
            print(f"\n{result['test_name']}")
            print("-" * 60)

            if "concurrent_requests" in result:
                print(f"  Type: Concurrent load test")
                print(f"  Concurrent requests: {result['concurrent_requests']}")
                print(f"  Total time: {result['total_time']:.2f}s")
            else:
                print(f"  Type: Sequential test")
                print(f"  Iterations: {result['iterations']}")

            print(f"  Success: {result['success_count']}")
            if result.get("error_count", 0) > 0:
                print(f"  Errors: {result['error_count']}")

            rt = result["response_times"]
            print(f"\n  Response Times:")
            print(f"    Mean:   {rt['mean']:.3f}s")
            print(f"    Median: {rt['median']:.3f}s")
            print(f"    Min:    {rt['min']:.3f}s")
            print(f"    Max:    {rt['max']:.3f}s")
            if "stdev" in rt:
                print(f"    StdDev: {rt['stdev']:.3f}s")
            if "p95" in rt:
                print(f"    P95:    {rt['p95']:.3f}s")
            if "p99" in rt:
                print(f"    P99:    {rt['p99']:.3f}s")

            if "throughput" in result:
                t = result["throughput"]
                print(f"\n  Throughput:")
                print(f"    Requests/sec: {t['requests_per_second']:.2f}")

            if "route_counts" in result:
                rc = result["route_counts"]
                print(f"\n  Routes Returned:")
                print(f"    Mean: {rc['mean']:.1f}")
                if "min" in rc:
                    print(f"    Min:  {rc['min']}")
                    print(f"    Max:  {rc['max']}")

            if "response_sizes" in result:
                rs = result["response_sizes"]
                print(f"\n  Response Size:")
                print(f"    Mean: {rs['mean_kb']:.2f} KB ({rs['mean_bytes']:.0f} bytes)")


def main():
    """Main function to run performance tests."""
    parser = argparse.ArgumentParser(description="Performance test for Stiflyt Route API")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the API server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of iterations per test (default: 10)",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=10,
        help="Number of concurrent requests for load test (default: 10)",
    )
    parser.add_argument(
        "--skip-concurrent",
        action="store_true",
        help="Skip concurrent load tests",
    )
    parser.add_argument(
        "--small-only",
        action="store_true",
        help="Run only the small bounding box test (with DNT filter)",
    )

    args = parser.parse_args()

    # Check if server is reachable
    print(f"Testing API at: {args.url}")
    try:
        response = requests.get(f"{args.url}/health", timeout=5)
        if response.status_code == 200:
            print("✓ Server is reachable\n")
        else:
            print(f"⚠️  Server returned status {response.status_code}\n")
    except requests.exceptions.RequestException as e:
        print(f"✗ Cannot reach server: {e}")
        print(f"  Make sure the backend is running: make backend")
        return 1

    tester = PerformanceTest(base_url=args.url)
    all_results = []

    if args.small_only:
        # Run only the small bounding box test with DNT filter
        result = tester.run_single_test(
            "Small BBox - DNT filter",
            min_lat=61.0,
            min_lng=8.0,
            max_lat=61.5,
            max_lng=8.5,
            organization="DNT",
            iterations=args.iterations,
        )
        all_results.append(result)
    else:
        # Test scenarios - using Norwegian coordinates (around Oslo/Jotunheimen area)
        # These are example coordinates - adjust based on your actual data

        # Test 1: Small bounding box (zoomed in)
        result1 = tester.run_single_test(
            "Small BBox (zoomed in) - No filter",
            min_lat=61.0,
            min_lng=8.0,
            max_lat=61.5,
            max_lng=8.5,
            iterations=args.iterations,
        )
        all_results.append(result1)

        # Test 2: Small bounding box with DNT filter
        result2 = tester.run_single_test(
            "Small BBox - DNT filter",
            min_lat=61.0,
            min_lng=8.0,
            max_lat=61.5,
            max_lng=8.5,
            organization="DNT",
            iterations=args.iterations,
        )
        all_results.append(result2)

        # Test 3: Medium bounding box
        result3 = tester.run_single_test(
            "Medium BBox - DNT filter",
            min_lat=60.0,
            min_lng=7.0,
            max_lat=62.0,
            max_lng=9.0,
            organization="DNT",
            iterations=args.iterations,
        )
        all_results.append(result3)

        # Test 4: Large bounding box
        result4 = tester.run_single_test(
            "Large BBox - DNT filter",
            min_lat=59.0,
            min_lng=6.0,
            max_lat=63.0,
            max_lng=10.0,
            organization="DNT",
            iterations=args.iterations,
        )
        all_results.append(result4)

        # Test 5: With prefix filter
        result5 = tester.run_single_test(
            "Small BBox - Prefix 'bre' filter",
            min_lat=61.0,
            min_lng=8.0,
            max_lat=61.5,
            max_lng=8.5,
            prefix="bre",
            iterations=args.iterations,
        )
        all_results.append(result5)

        # Test 6: Concurrent load test
        if not args.skip_concurrent:
            result6 = tester.run_concurrent_test(
                "Concurrent Load Test - DNT filter",
                min_lat=61.0,
                min_lng=8.0,
                max_lat=61.5,
                max_lng=8.5,
                organization="DNT",
                concurrent_requests=args.concurrent,
            )
            all_results.append(result6)

    # Print summary
    tester.print_summary(all_results)

    return 0


if __name__ == "__main__":
    exit(main())
