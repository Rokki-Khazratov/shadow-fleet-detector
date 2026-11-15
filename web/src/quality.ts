export interface QualityReport {
  observed_points: number;
  conflict_count: number;
  clock_skew_count: number;
  interval_status: 'assessed' | 'truncated' | 'insufficient';
  long_interval_threshold_seconds: number;
  long_interval_count: number | null;
  long_intervals: {before: string; after: string; duration_seconds: number}[];
}

export function qualityDetails(report: QualityReport) {
  const details = document.createElement('details');
  details.className = 'quality-details';
  const summary = document.createElement('summary');
  summary.textContent = 'Качество наблюдений AIS';
  details.append(summary);
  const paragraph = (message: string) => {
    const p = document.createElement('p');
    p.textContent = message;
    details.append(p);
  };
  paragraph(`Точек в ответе: ${report.observed_points}. Конфликтов времени: ${report.conflict_count}. Сдвигов часов источника: ${report.clock_skew_count}.`);
  if (report.interval_status === 'truncated') {
    paragraph('Ответ усечён; интервалы за всё окно не оценены.');
  } else if (report.interval_status === 'insufficient') {
    paragraph('Для оценки интервала нужны хотя бы две точки.');
  } else {
    paragraph(`Интервалы ≥ ${report.long_interval_threshold_seconds / 60} мин: ${report.long_interval_count}.`);
    if (report.long_intervals.length) {
      const list = document.createElement('ul');
      list.className = 'history-list';
      for (const interval of report.long_intervals) {
        const row = document.createElement('li');
        row.textContent = `${new Date(interval.before).toISOString()} → ${new Date(interval.after).toISOString()} · ${Math.round(interval.duration_seconds)} с`;
        list.append(row);
      }
      details.append(list);
      if ((report.long_interval_count ?? 0) > report.long_intervals.length) {
        paragraph(`Показаны первые ${report.long_intervals.length} интервалов.`);
      }
    }
    paragraph('Причина интервалов неизвестна.');
  }
  return details;
}
