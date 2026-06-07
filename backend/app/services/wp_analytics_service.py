"""Per-site WordPress traffic + error analytics (#25).

Docker-correct: managed WP sites are official ``wordpress:*-apache`` containers
that send the Apache *combined* access log to the container's stdout, so
``docker logs <container>`` is the source (the in-container access.log is a
symlink to stdout — exec-cat'ing it yields nothing). Analytics is computed
**on demand** over a recent window; there is no separate store, so history is
bounded by the container's retained log (it resets when the container is
recreated, e.g. on a PHP-version switch — see #24).

Intentionally NOT derived from the default access log (deferred):
- PHP fatals — need ``wp-content/debug.log``, which only exists once WP_DEBUG_LOG
  is enabled (the per-site WP_DEBUG toggle is #30).
- per-request response time / slow pages — need a ``%D`` LogFormat the official
  image does not emit.
- cache hit ratio — a cache-plugin concern surfaced by #22/#23, not the access log.
"""

import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone


# Apache "combined" CustomLog (the official wordpress:*-apache default to stdout):
#   %h %l %u %t "%r" %>s %b "%{Referer}i" "%{User-Agent}i"
_ACCESS_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\S+) '
    r'"(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)
_BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|mediapartners|facebookexternalhit|embedly|bingpreview|monitor|wget|curl|python-requests',
    re.IGNORECASE,
)
_APACHE_TIME_FMT = '%d/%b/%Y:%H:%M:%S %z'


class WpAnalyticsService:
    """On-demand per-site traffic/error analytics from the apache access log."""

    MAX_HOURS = 168       # cap the window at 7 days
    TAIL_CAP = 20000      # cap the docker-logs pull so a busy site can't blow up memory
    LOG_TIMEOUT = 15      # seconds; bound the synchronous docker-logs pull (single-worker safety)

    @classmethod
    def get_traffic(cls, container_name, hours=24):
        try:
            hours = int(hours)
        except (TypeError, ValueError):
            hours = 24
        hours = max(1, min(hours, cls.MAX_HOURS))

        result = cls._empty(hours)
        if not container_name:
            result['note'] = 'No container is resolved for this site.'
            return result

        # Pull the access log straight from the container's stdout with a hard
        # timeout so a busy site / hung daemon can't block the (single) worker.
        # Reading only stdout cleanly separates the access log from the error_log
        # (which Apache sends to stderr).
        try:
            proc = subprocess.run(
                ['docker', 'logs', '--tail', str(cls.TAIL_CAP), '--since', f'{hours}h', container_name],
                capture_output=True, text=True, timeout=cls.LOG_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            result['note'] = 'Traffic log timed out — the site may be under heavy load; try a shorter window.'
            return result
        except (FileNotFoundError, OSError):
            result['note'] = 'Traffic log is unavailable on this host (Docker is not reachable).'
            return result

        if proc.returncode != 0:
            # e.g. "Error: No such container" — stopped / removed / on a remote agent.
            result['note'] = 'Traffic log is unavailable — the container may be stopped or running on another host.'
            return result

        lines = (proc.stdout or '').splitlines()

        # Pre-seed continuous hourly buckets so the chart x-axis has no gaps.
        now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        buckets = {now_hour - timedelta(hours=i): {'requests': 0, 'errors': 0}
                   for i in range(hours, -1, -1)}

        ips = set()
        total = 0
        bytes_total = 0
        bots = 0
        not_found = 0
        status_buckets = {'2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0}
        paths = Counter()

        for raw in lines:
            m = _ACCESS_RE.match(raw.strip())
            if not m:
                continue  # error_log / PHP / non-access lines won't match
            status = int(m.group('status'))
            total += 1
            ips.add(m.group('ip'))

            b = m.group('bytes')
            if b.isdigit():
                bytes_total += int(b)

            bucket = f'{status // 100}xx'
            if bucket in status_buckets:
                status_buckets[bucket] += 1
            if status == 404:
                not_found += 1
            if _BOT_RE.search(m.group('ua')):
                bots += 1

            req_parts = m.group('request').split(' ')
            path = req_parts[1] if len(req_parts) >= 2 else m.group('request')
            paths[path.split('?', 1)[0]] += 1  # group by route; drop query strings (may carry tokens)

            try:
                t = datetime.strptime(m.group('time'), _APACHE_TIME_FMT).astimezone(timezone.utc)
                hk = t.replace(minute=0, second=0, microsecond=0)
                if hk in buckets:
                    buckets[hk]['requests'] += 1
                    if status >= 400:
                        buckets[hk]['errors'] += 1
            except (ValueError, OverflowError):
                pass

        if total == 0:
            result['note'] = (
                f'No requests recorded in the last {hours}h — the site may be idle, '
                'stopped, or recently recreated (the access log resets on recreate).'
            )
            return result

        errors = status_buckets['4xx'] + status_buckets['5xx']
        result.update({
            'requests': total,
            'unique_visitors': len(ips),
            'bytes': bytes_total,
            'bytes_human': cls._human_bytes(bytes_total),
            'status': status_buckets,
            'not_found': not_found,
            'bot_requests': bots,
            'bot_pct': round(bots / total * 100, 1),
            'error_rate': round(errors / total * 100, 1),
            'top_paths': [{'path': p, 'count': c} for p, c in paths.most_common(10)],
            'series': [{'hour': k.isoformat(), 'requests': v['requests'], 'errors': v['errors']}
                       for k, v in sorted(buckets.items())],
            'note': None,
        })
        return result

    @classmethod
    def _empty(cls, hours):
        now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        series = [{'hour': (now_hour - timedelta(hours=i)).isoformat(), 'requests': 0, 'errors': 0}
                  for i in range(hours, -1, -1)]
        return {
            'success': True,
            'window_hours': hours,
            'requests': 0,
            'unique_visitors': 0,
            'bytes': 0,
            'bytes_human': '0 B',
            'status': {'2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0},
            'not_found': 0,
            'bot_requests': 0,
            'bot_pct': 0.0,
            'error_rate': 0.0,
            'top_paths': [],
            'series': series,
            'note': None,
        }

    @staticmethod
    def _human_bytes(n):
        size = float(n)
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if size < 1024 or unit == 'TB':
                return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
            size /= 1024
