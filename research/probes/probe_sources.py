"""Bounded read-only source experiments; standard library only, no application."""
import concurrent.futures
import datetime as dt
import hashlib
import gzip
import json
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request

OUT = Path(__file__).parent / 'results'
LIMIT = 8_000_000
SOURCES = {
    'digitraffic_locations': 'https://meri.digitraffic.fi/api/ais/v1/locations',
    'digitraffic_vessels': 'https://meri.digitraffic.fi/api/ais/v1/vessels',
    'aisstream_docs': 'https://www.aisstream.io/documentation/',
    'gfw_without_token': 'https://gateway.api.globalfishingwatch.org/v3/vessels/search?query=EXAMPLE',
    'opensanctions_catalog': 'https://data.opensanctions.org/datasets/latest/index.json',
    'noaa_catalog': 'https://www.fisheries.noaa.gov/inport/item/80362',
    'danish_catalog': 'https://www.dma.dk/safety-at-sea/navigational-information/ais-data',
}


def http_probe(item):
    name, url = item
    result = {'source': name, 'url': url, 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'method': 'GET', 'credentials_used': False}
    start = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'ShadowFleetDetector-research/0.1', 'Digitraffic-User': 'ShadowFleetDetector/research', 'Accept-Encoding': 'gzip'})
        try:
            response = urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            result.update(http_status=response.code, final_url=response.url, content_type=response.headers.get('Content-Type'), server_date=response.headers.get('Date'))
            body = response.read(LIMIT + 1)
            if response.headers.get('Content-Encoding') == 'gzip':
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                    body = stream.read(LIMIT + 1)
        result['truncated'] = len(body) > LIMIT
        body = body[:LIMIT]
        result.update(bytes_read=len(body), sha256=hashlib.sha256(body).hexdigest())
        try:
            payload = json.loads(body)
            result['format'] = 'json'
            if name == 'digitraffic_locations':
                features = payload.get('features', [])
                result.update(top_level_keys=list(payload), feature_count=len(features), sample=features[:2])
            elif name == 'digitraffic_vessels':
                result.update(record_count=len(payload), sample=payload[:2] if isinstance(payload, list) else payload)
            elif name == 'opensanctions_catalog':
                result['top_level_keys'] = list(payload)[:20] if isinstance(payload, dict) else []
                result['sample'] = {'note': 'Catalog reachable; entity datasets not downloaded.'}
            else:
                result['sample'] = payload
        except (ValueError, TypeError):
            result['format'] = 'non-json'
            result['sample'] = body.decode('utf-8', errors='replace')[:350]
        result['outcome'] = 'http_success' if 200 <= response.code < 300 else 'http_error'
    except Exception as exc:
        result.update(outcome='transport_error', error_type=type(exc).__name__, error=str(exc))
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    return result


def tcp_probe():
    result = {'source': 'kystverket_tcp', 'endpoint': '153.44.253.27:5631', 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'credentials_used': False}
    try:
        with socket.create_connection(('153.44.253.27', 5631), timeout=10) as connection:
            connection.settimeout(10)
            body = connection.recv(4096)
        lines = body.decode('ascii', errors='replace').splitlines()
        result.update(outcome='bytes_received' if body else 'empty_stream', bytes_read=len(body), sample=lines[:2], format='NMEA/IEC text, not JSON', sha256=hashlib.sha256(body).hexdigest())
    except Exception as exc:
        result.update(outcome='transport_error', error_type=type(exc).__name__, error=str(exc))
    return result


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(http_probe, SOURCES.items()))
    results.append(tcp_probe())
    for result in results:
        (OUT / (result['source'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps([{k: r[k] for k in ('source', 'outcome', 'http_status', 'feature_count', 'record_count', 'bytes_read', 'error') if k in r} for r in results], indent=2))
