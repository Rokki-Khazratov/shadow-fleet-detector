"""Create the local chart assets from pinned Natural Earth v5.1.2 GeoJSON."""
import argparse
import json
from pathlib import Path

LABELS = {'Helsinki': 'Хельсинки', 'Tallinn': 'Таллин', 'Tampere': 'Тампере',
          'St.  Petersburg': 'Санкт-Петербург', 'Pskov': 'Псков', 'Stockholm': 'Стокгольм'}


def coordinates(value):
    if isinstance(value, list):
        return [coordinates(item) for item in value]
    return round(value, 4)


def write(path, data):
    path.write_text(json.dumps(data, separators=(',', ':'), ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('land', type=Path)
    parser.add_argument('places', type=Path)
    parser.add_argument('output', type=Path, default=Path('web/public/map'), nargs='?')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    land = json.loads(args.land.read_text())
    features = [{'type': 'Feature', 'properties': {}, 'geometry': {
        'type': f['geometry']['type'], 'coordinates': coordinates(f['geometry']['coordinates']),
    }} for f in land['features']]
    write(args.output / 'land.geojson', {'type': 'FeatureCollection', 'features': features})
    places = json.loads(args.places.read_text())
    labels = [{'label': LABELS[f['properties']['name']], 'coordinates': coordinates(f['geometry']['coordinates'])}
              for f in places['features'] if f['properties']['name'] in LABELS]
    if len(labels) != len(LABELS):
        raise ValueError('Not all expected geographic labels were present')
    write(args.output / 'places.json', labels)


if __name__ == '__main__':
    main()
