import { Popup, type FilterSpecification, type GeoJSONSource, type Map as MapLibreMap, type MapMouseEvent } from 'maplibre-gl';
import type { Theme } from './chart';
import { historyTime, type HistoryPoint } from './history';
import { element } from './workspace';

export function historyLayer(map: MapLibreMap, legend: HTMLElement) {
  const id = 'history-points';
  const halo = 'history-selected';
  let points = new Map<string,HistoryPoint>();
  let onActive: ((point: HistoryPoint | null) => void) | undefined;
  let active: HistoryPoint | null = null;
  let popup: Popup | undefined;
  const filter = (time: string): FilterSpecification => ['==',['get','provider_time'],time];
  map.addSource(id,{type:'geojson',data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id,type:'circle',source:id,paint:{
    'circle-radius':7.5, 'circle-color':'#f0c785', 'circle-stroke-color':'#101923', 'circle-stroke-width':1,
  }},'points');
  map.addLayer({id:halo,type:'circle',source:id,filter:filter(''),paint:{
    'circle-radius':10.5, 'circle-color':'transparent', 'circle-stroke-color':'#f0c785', 'circle-stroke-width':1.5,
  }},'points');

  function mark(point: HistoryPoint | null) {
    active = point;
    map.setFilter(halo,filter(point?.provider_time ?? ''));
    onActive?.(point);
  }

  function dismiss() {
    const previous = popup;
    popup = undefined;
    previous?.remove();
    if (active) mark(null);
  }

  function show(point: HistoryPoint, worldLon: number, returnFocus?: () => void) {
    if (active === point) {
      dismiss();
      return;
    }
    dismiss();
    const lon = point.lon + 360 * Math.round((worldLon - point.lon) / 360);
    const at: [number,number] = [lon,point.lat];
    if (returnFocus && !map.getBounds().contains(at)) map.jumpTo({center:at});
    const content = element('div','','history-popup-data');
    const time = element('time',historyTime(point.provider_time));
    time.dateTime = point.provider_time;
    content.append(time,element('span',`${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}`));
    if (point.time_conflict) content.append(element('span','Конфликт времени','warning'));
    const next = new Popup({closeOnClick:false,focusAfterOpen:false,className:'history-popup'})
      .setLngLat(at).setDOMContent(content).addTo(map);
    popup = next;
    next.getElement().querySelector('.maplibregl-popup-close-button')?.setAttribute('aria-label','Закрыть историческую точку');
    next.on('close',() => {
      if (popup !== next) return;
      popup = undefined;
      mark(null);
      returnFocus?.();
    });
    mark(point);
    if (returnFocus && window.matchMedia('(max-width: 760px)').matches) {
      map.getContainer().scrollIntoView({block:'nearest'});
      map.getCanvas().focus({preventScroll:true});
    }
  }

  map.getCanvas().addEventListener('keydown',event => {
    if (event.key === 'Escape' && popup) {
      event.preventDefault();
      popup.remove();
    }
  });

  return {
    replace(items: HistoryPoint[], activeChanged?: (point: HistoryPoint | null) => void) {
      dismiss();
      onActive = activeChanged;
      points = new Map(items.map(point => [point.provider_time,point]));
      legend.hidden = !items.length;
      (map.getSource(id) as GeoJSONSource).setData({type:'FeatureCollection',features:items.map(p => ({
        type:'Feature', geometry:{type:'Point',coordinates:[p.lon,p.lat]},
        properties:{provider_time:p.provider_time},
      }))});
    },
    inspect(point: HistoryPoint, returnFocus: () => void) {
      if (points.get(point.provider_time) === point) show(point,map.getCenter().lng,returnFocus);
    },
    inspectAt(event: MapMouseEvent) {
      const features = map.queryRenderedFeatures(event.point,{layers:[id]});
      const time = features[0]?.properties.provider_time;
      const point = typeof time === 'string' ? points.get(time) : undefined;
      if (point) show(point,event.lngLat.lng);
    },
    applyTheme(theme: Theme) {
      const history = theme === 'dark' ? '#f0c785' : '#80502a';
      map.setPaintProperty(id,'circle-color',history);
      map.setPaintProperty(id,'circle-stroke-color',theme === 'dark' ? '#101923' : '#f6f8fc');
      map.setPaintProperty(halo,'circle-stroke-color',history);
    },
  };
}

export type HistoryOverlay = ReturnType<typeof historyLayer>;
