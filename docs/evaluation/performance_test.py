#!/usr/bin/env python3
"""Performance efficiency test (SOP 5.3) -- stdlib only, no extra dependency.

Hits a running instance of the app under configurable concurrency and reports
response-time percentiles per endpoint. This is a light substitute for a full
load-testing tool (Locust/k6): appropriate for reporting response times under
a modest number of concurrent barangay health workers, not for claiming
internet-scale throughput.

Usage:
    # Start the app first (in another terminal):
    #   python app.py
    #
    # Then, from the project root:
    python docs/evaluation/performance_test.py
    python docs/evaluation/performance_test.py --base-url http://127.0.0.1:5000 \\
        --username admin --password <your-admin-password> \\
        --requests 50 --concurrency 10

Without --username/--password, only unauthenticated routes are tested and a
note is printed for the routes that were skipped.
"""

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from urllib.parse import urlencode


def login(base_url, username, password):
    """Return a Cookie header value for an authenticated session, or None."""
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    data = urlencode({"username": username, "password": password}).encode("utf-8")
    request = Request(base_url + "/login", data=data, method="POST")
    try:
        opener.open(request, timeout=10)
    except (HTTPError, URLError) as exc:
        print(f"Login failed: {exc}")
        return None
    cookies = "; ".join(f"{c.name}={c.value}" for c in jar)
    if not cookies:
        print("Login did not return a session cookie -- check credentials.")
        return None
    return cookies


def timed_request(url, cookie_header=None):
    headers = {"Cookie": cookie_header} if cookie_header else {}
    request = Request(url, headers=headers)
    start = time.perf_counter()
    try:
        with build_opener().open(request, timeout=10) as response:
            response.read()
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except URLError:
        status = None
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, status


def run_endpoint(base_url, path, count, concurrency, cookie_header=None):
    url = base_url + path
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(timed_request, url, cookie_header) for _ in range(count)]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def percentile(sorted_values, pct):
    if not sorted_values:
        return float("nan")
    index = min(len(sorted_values) - 1, int(round((pct / 100) * (len(sorted_values) - 1))))
    return sorted_values[index]


def report(path, results):
    times = sorted(r[0] for r in results)
    statuses = [r[1] for r in results]
    errors = sum(1 for s in statuses if s is None or s >= 400)
    print(f"\n{path}")
    print(f"  requests: {len(results)}   errors: {errors}")
    if times:
        print(
            f"  min={times[0]:.1f}ms  mean={statistics.mean(times):.1f}ms  "
            f"p50={percentile(times, 50):.1f}ms  p95={percentile(times, 95):.1f}ms  max={times[-1]:.1f}ms"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--username", default=None, help="Account to log in as, to test authenticated routes")
    parser.add_argument("--password", default=None)
    parser.add_argument("--requests", type=int, default=30, help="Requests per endpoint")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers per endpoint")
    args = parser.parse_args()

    print(f"Target: {args.base_url}   requests/endpoint={args.requests}   concurrency={args.concurrency}")

    public_routes = ["/login", "/register"]
    authenticated_routes = ["/dashboard", "/api/dashboard", "/api/facilities"]

    for path in public_routes:
        results = run_endpoint(args.base_url, path, args.requests, args.concurrency)
        report(path, results)

    cookie_header = None
    if args.username and args.password:
        cookie_header = login(args.base_url, args.username, args.password)

    if cookie_header:
        for path in authenticated_routes:
            results = run_endpoint(args.base_url, path, args.requests, args.concurrency, cookie_header)
            report(path, results)
    else:
        print(
            f"\nSkipped authenticated routes ({', '.join(authenticated_routes)}) "
            "-- pass --username/--password to include them."
        )


if __name__ == "__main__":
    main()
