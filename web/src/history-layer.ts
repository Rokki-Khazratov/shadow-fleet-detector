import { Popup, type GeoJSONSource, type Map } from 'maplibre-gl';
import type { HistoryPoint } from './history';

export function historyLayer(map: Map, legend: HTMLElement) {
  const id = 'history-points';
  let popup: Popup | undefined;
  map.addSource(id, {type:'geojson', data:{type:'FeatureCollection', features:[]}});
  map.addLayer({id, type:'circle', source:id, paint:{
    'circle-radius':5, 'circle-color':'#f0c785', 'circle-stroke-color':'#101b23', 'circle-stroke-width':1,
  }}, 'points');
  map.on('click', id, event => {
    const point = event.features?.[0];
    if (point?.geometry.type !== 'Point') return;
    const [lon, lat] = point.geometry.coordinates;
    popup?.remove();
    popup = new Popup({focusAfterOpen:false, className:'history-popup'})
      .setLngLat(event.lngLat)
      .setText(`${point.properties.provider_time} · ${lat.toFixed(4)}, ${lon.toFixed(4)}`)
      .addTo(map);
  });
  return (points: HistoryPoint[]) => {
    popup?.remove();
    legend.hidden = !points.length;
    (map.getSource(id) as GeoJSONSource).setData({type:'FeatureCollection', features:points.map(p => ({
      type:'Feature', geometry:{type:'Point', coordinates:[p.lon,p.lat]},
      properties:{provider_time:p.provider_time},
    }))});
  };
}
