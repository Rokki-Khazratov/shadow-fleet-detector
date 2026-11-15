import type {Position, Source} from './types';

const timestamp = Date.now();
const iso = (age: number) => new Date(timestamp - age * 1000).toISOString();
const source: Source = {
  id:'synthetic', attribution:'Синтетический набор', license_url:'', sync_state:'starting',
  last_mqtt_at:null, last_snapshot_at:null,
};
const seeds = [
  [25.08, 59.95, 22, 12.4, 81], [24.61, 59.84, 38, 9.1, 278],
  [26.32, 60.04, 56, 13.6, 96], [24.26, 59.63, 78, 0, null],
  [27.37, 60.05, 109, 10.8, 75], [23.77, 59.56, 132, 7.2, 245],
  [25.71, 59.79, 185, 5.7, 114], [28.09, 59.99, 347, 11.2, 86],
  [22.45, 59.55, 380, 12.8, 267], [27.02, 59.77, 415, null, null],
] as const;
const points: Position[] = seeds.map(([lon,lat,age,speed,course], index) => ({
  source_id:source.id, mmsi:String(900000001 + index), lon, lat,
  provider_time:iso(age), received_at:iso(age - 2), age_seconds:age, stale:age > 300,
  transport:'mqtt', time_conflict:false, clock_skew:false, sog_kn:speed, cog_deg:course, heading_deg:null,
}));

export function demoResponse(path: string): Response {
  const url = new URL(path, window.location.origin);
  const [, , route, provider, id] = url.pathname.split('/');
  if (route === 'positions' && provider === undefined) {
    const [west, south, east, north] = ['west', 'south', 'east', 'north'].map(key => Number(url.searchParams.get(key)));
    const items = points.filter(p => p.lat >= south && p.lat <= north && (west <= east
      ? p.lon >= west && p.lon <= east : p.lon >= west || p.lon <= east));
    return Response.json({as_of:iso(0), source, items, truncated:false});
  }
  const item = provider === source.id && points.find(p => p.mmsi === id);
  if (!item) return Response.json({error:{code:'not_found'}}, {status:404});
  if (route === 'positions') return Response.json({as_of:iso(0), source, item});
  if (route === 'dossier') {
    return Response.json({status:'not_configured', on:url.searchParams.get('on'), bindings:[], external_claims:[]});
  }
  if (route === 'history') {
    const start = Date.parse(url.searchParams.get('from') ?? '');
    const end = Date.parse(url.searchParams.get('to') ?? '');
    const offsets = [1070, 660, 370, 265, 144, 69, 28, 19, 11, 6, 2];
    const items = offsets.map((minutes, i) => ({...item,
      provider_time:iso(item.age_seconds + minutes*60), lon:item.lon - (offsets.length-i)*0.035,
      lat:item.lat - (offsets.length-i)*0.008,
    })).filter(p => Date.parse(p.provider_time) >= start && Date.parse(p.provider_time) < end);
    const threshold = 900;
    const longIntervals = items.slice(1).flatMap((after,i) => {
      const before = items[i]!.provider_time;
      const seconds = (Date.parse(after.provider_time) - Date.parse(before)) / 1000;
      return seconds < threshold ? [] : [{before,after:after.provider_time,duration_seconds:seconds}];
    });
    return Response.json({source, mmsi:item.mmsi, items, truncated:false, quality:{
      observed_points:items.length, conflict_count:0, clock_skew_count:0,
      interval_status:items.length > 1 ? 'assessed' : 'insufficient',
      long_interval_threshold_seconds:threshold, long_interval_count:items.length > 1 ? longIntervals.length : null,
      long_intervals:longIntervals,
    }});
  }
  return Response.json({error:{code:'not_found'}}, {status:404});
}
