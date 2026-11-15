import {Map, Marker, NavigationControl, ScaleControl, type GeoJSONSource} from 'maplibre-gl';
import type {FeatureCollection, LineString, Point} from 'geojson';
import type {Position} from './types';

export type Theme = 'dark' | 'light';
const palette = {
  dark: {water:'#101923', land:'#252e39', coast:'#566270', grid:'#7790a8', fresh:'#8cb3ff', stale:'#9aa6b4', stroke:'#101923', selection:'#a7c4ff'},
  light: {water:'#e7edf6', land:'#c7cbd0', coast:'#7b8794', grid:'#75869a', fresh:'#174db6', stale:'#56616f', stroke:'#f6f8fc', selection:'#214eb0'},
};
const grid: FeatureCollection<LineString> = {type:'FeatureCollection',features:[]};
for (let lon = -180; lon < 180; lon++) {
  grid.features.push({type:'Feature',properties:{major:lon % 5 === 0},geometry:{type:'LineString',coordinates:[[lon,-80],[lon,80]]}});
}
for (let lat = -80; lat <= 80; lat++) {
  // Split parallels so the renderer never wraps a single segment across the antimeridian.
  for (let lon = -180; lon < 180; lon += 60) {
    grid.features.push({type:'Feature',properties:{major:lat % 5 === 0},geometry:{type:'LineString',coordinates:[[lon,lat],[lon+60,lat]]}});
  }
}
const empty: FeatureCollection<Point> = {type:'FeatureCollection',features:[]};
const mapAsset = (file: string) => `${import.meta.env.BASE_URL}map/${file}`;

export function createChart(theme: Theme) {
  const colors = palette[theme];
  const map = new Map({
    container:'map', center:[25,60], zoom:6, attributionControl:false,
    pitchWithRotate:false, dragRotate:false, maxZoom:11,
    style:{version:8, transition:{duration:0,delay:0}, sources:{land:{type:'geojson',data:mapAsset('land.geojson')},
      'chart-grid':{type:'geojson',data:grid}, positions:{type:'geojson',data:empty}}, layers:[
      {id:'water',type:'background',paint:{'background-color':colors.water}},
      {id:'land',type:'fill',source:'land',paint:{'fill-color':colors.land,'fill-antialias':false}},
      {id:'grid',type:'line',source:'chart-grid',minzoom:3,paint:{'line-color':colors.grid,
        'line-opacity':['case',['get','major'],0.19,0.085], 'line-width':1}},
      {id:'coast',type:'line',source:'land',paint:{'line-color':colors.coast,'line-width':0.9}},
      {id:'points',type:'circle',source:'positions',paint:{
        'circle-radius':['case',['get','selected'],5.5,4],
        'circle-color':['case',['get','stale'],colors.stale,colors.fresh],
        'circle-stroke-color':colors.stroke,'circle-stroke-width':1}},
    ]},
  });
  map.getCanvas().setAttribute('aria-label', 'Интерактивная морская карта');
  map.addControl(new NavigationControl({showCompass:false}), 'bottom-right');
  map.addControl(new ScaleControl({unit:'metric',maxWidth:100}), 'bottom-left');
  const reticle = document.createElement('span');
  reticle.className = 'reticle';
  reticle.setAttribute('aria-hidden','true');
  const target = new Marker({element:reticle,rotationAlignment:'viewport'});
  const labels: Marker[] = [];
  const abort = new AbortController();
  const syncLabels = () => {
    for (const label of labels) label.getElement().hidden = map.getZoom() < 4.8;
  };
  map.on('zoomend', syncLabels);
  void fetch(mapAsset('places.json'), {signal:abort.signal}).then(response => {
    if (!response.ok) throw Error('places');
    return response.json() as Promise<{label:string;coordinates:[number,number]}[]>;
  }).then(places => {
    if (abort.signal.aborted) return;
    for (const place of places) {
      const element = document.createElement('span');
      element.className = 'place-label';
      element.textContent = place.label;
      labels.push(new Marker({element, anchor:'left', offset:[3,0]}).setLngLat(place.coordinates).addTo(map));
    }
    syncLabels();
  }).catch(() => {}); // Coastlines and observations still work without supplementary labels.

  const applyTheme = (theme: Theme) => {
    if (!map.getLayer('water')) return;
    const c = palette[theme];
    map.setPaintProperty('water','background-color',c.water);
    map.setPaintProperty('land','fill-color',c.land);
    map.setPaintProperty('coast','line-color',c.coast);
    map.setPaintProperty('grid','line-color',c.grid);
    map.setPaintProperty('points','circle-color',['case',['get','stale'],c.stale,c.fresh]);
    map.setPaintProperty('points','circle-stroke-color',c.stroke);
  };
  const positions = (points: Position[], selected: Position | undefined) => {
    (map.getSource('positions') as GeoJSONSource | undefined)?.setData({type:'FeatureCollection',features:points.map(p => ({
      type:'Feature',geometry:{type:'Point',coordinates:[p.lon,p.lat]},properties:{mmsi:p.mmsi,
        source_id:p.source_id,stale:p.stale,selected:p === selected},
    }))});
    if (selected) target.setLngLat([selected.lon,selected.lat]).addTo(map);
    else target.remove();
  };
  const cleanup = () => {abort.abort(); target.remove(); labels.forEach(marker => marker.remove()); map.remove();};
  return {map, applyTheme, positions, cleanup};
}
