import type {
  BoxplotPoint,
  ComparativeHistogramBin,
  CurvePoint,
  DuplicateFrequencyPoint,
  FirstDigitPoint,
  HistogramBin,
  QQPoint,
  SampleMetricPoint,
} from "../../lib/types";

const WIDTH = 860;
const HEIGHT = 320;
const PAD_LEFT = 48;
const PAD_RIGHT = 20;
const PAD_TOP = 16;
const PAD_BOTTOM = 40;

function chartBounds() {
  const innerWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
  const innerHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  return { innerWidth, innerHeight };
}

function axisLine() {
  return (
    <>
      <line
        x1={PAD_LEFT}
        y1={HEIGHT - PAD_BOTTOM}
        x2={WIDTH - PAD_RIGHT}
        y2={HEIGHT - PAD_BOTTOM}
        stroke="#cbd5e1"
        strokeWidth={1}
      />
      <line
        x1={PAD_LEFT}
        y1={PAD_TOP}
        x2={PAD_LEFT}
        y2={HEIGHT - PAD_BOTTOM}
        stroke="#cbd5e1"
        strokeWidth={1}
      />
    </>
  );
}

function axisLabels(xLabel?: string, yLabel?: string) {
  return (
    <>
      {xLabel ? (
        <text
          x={(PAD_LEFT + (WIDTH - PAD_RIGHT)) / 2}
          y={HEIGHT - 8}
          textAnchor="middle"
          fontSize="12"
          fill="#334155"
        >
          {xLabel}
        </text>
      ) : null}
      {yLabel ? (
        <text
          x={14}
          y={(PAD_TOP + (HEIGHT - PAD_BOTTOM)) / 2}
          textAnchor="middle"
          fontSize="12"
          fill="#334155"
          transform={`rotate(-90 14 ${(PAD_TOP + (HEIGHT - PAD_BOTTOM)) / 2})`}
        >
          {yLabel}
        </text>
      ) : null}
    </>
  );
}

export function HistogramPlot({
  bins,
  color = "#0f172a",
  xLabel,
  yLabel,
}: {
  bins: HistogramBin[];
  color?: string;
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
  const barWidth = bins.length > 0 ? innerWidth / bins.length : innerWidth;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {bins.map((bin, index) => {
        const barHeight = (bin.count / maxCount) * innerHeight;
        const x = PAD_LEFT + index * barWidth;
        const y = HEIGHT - PAD_BOTTOM - barHeight;
        return (
          <rect
            key={`${bin.start}-${bin.end}-${index}`}
            x={x}
            y={y}
            width={Math.max(1, barWidth - 1)}
            height={barHeight}
            fill={color}
            opacity={0.85}
          />
        );
      })}
    </svg>
  );
}

export function DualHistogramPlot({
  bins,
  leftColor = "#0f172a",
  rightColor = "#0ea5e9",
  xLabel,
  yLabel,
}: {
  bins: ComparativeHistogramBin[];
  leftColor?: string;
  rightColor?: string;
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const maxCount = Math.max(
    1,
    ...bins.flatMap((bin) => [bin.leftCount, bin.rightCount])
  );
  const groupWidth = bins.length > 0 ? innerWidth / bins.length : innerWidth;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {bins.map((bin, index) => {
        const leftHeight = (bin.leftCount / maxCount) * innerHeight;
        const rightHeight = (bin.rightCount / maxCount) * innerHeight;
        const x = PAD_LEFT + index * groupWidth;
        const barW = Math.max(1, (groupWidth - 2) / 2);

        return (
          <g key={`${bin.start}-${bin.end}-${index}`}>
            <rect
              x={x}
              y={HEIGHT - PAD_BOTTOM - leftHeight}
              width={barW}
              height={leftHeight}
              fill={leftColor}
              opacity={0.85}
            />
            <rect
              x={x + barW}
              y={HEIGHT - PAD_BOTTOM - rightHeight}
              width={barW}
              height={rightHeight}
              fill={rightColor}
              opacity={0.85}
            />
          </g>
        );
      })}
    </svg>
  );
}

export function HistogramWithCurvePlot({
  bins,
  curve,
  xLabel,
  yLabel,
}: {
  bins: HistogramBin[];
  curve: CurvePoint[];
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
  const barWidth = bins.length > 0 ? innerWidth / bins.length : innerWidth;

  const minX = curve.length > 0 ? Math.min(...curve.map((p) => p.x)) : 0;
  const maxX = curve.length > 0 ? Math.max(...curve.map((p) => p.x)) : 1;
  const maxY = curve.length > 0 ? Math.max(...curve.map((p) => p.y), 1e-9) : 1;

  const path = curve
    .map((point, index) => {
      const xNorm = maxX === minX ? 0 : (point.x - minX) / (maxX - minX);
      const yNorm = point.y / maxY;
      const x = PAD_LEFT + xNorm * innerWidth;
      const y = HEIGHT - PAD_BOTTOM - yNorm * innerHeight;
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {bins.map((bin, index) => {
        const barHeight = (bin.count / maxCount) * innerHeight;
        const x = PAD_LEFT + index * barWidth;
        const y = HEIGHT - PAD_BOTTOM - barHeight;
        return (
          <rect
            key={`${bin.start}-${bin.end}-${index}`}
            x={x}
            y={y}
            width={Math.max(1, barWidth - 1)}
            height={barHeight}
            fill="#0f172a"
            opacity={0.35}
          />
        );
      })}
      {curve.length > 1 ? (
        <path d={path} fill="none" stroke="#ef4444" strokeWidth={2} />
      ) : null}
    </svg>
  );
}

export function QQScatterPlot({
  points,
  fitLine = [],
  xLabel,
  yLabel,
}: {
  points: QQPoint[];
  fitLine?: CurvePoint[];
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const minX = points.length > 0 ? Math.min(...points.map((p) => p.theoretical)) : -1;
  const maxX = points.length > 0 ? Math.max(...points.map((p) => p.theoretical)) : 1;
  const minY = points.length > 0 ? Math.min(...points.map((p) => p.sample)) : -1;
  const maxY = points.length > 0 ? Math.max(...points.map((p) => p.sample)) : 1;

  const mapX = (value: number) =>
    PAD_LEFT + (maxX === minX ? 0.5 : (value - minX) / (maxX - minX)) * innerWidth;
  const mapY = (value: number) =>
    HEIGHT - PAD_BOTTOM - (maxY === minY ? 0.5 : (value - minY) / (maxY - minY)) * innerHeight;

  const fitPath =
    fitLine.length >= 2
      ? fitLine
          .map((point, index) => `${index === 0 ? "M" : "L"} ${mapX(point.x)} ${mapY(point.y)}`)
          .join(" ")
      : "";

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {fitPath ? <path d={fitPath} fill="none" stroke="#ef4444" strokeWidth={2} /> : null}
      {points.map((point, idx) => {
        const x = mapX(point.theoretical);
        const y = mapY(point.sample);
        return <circle key={idx} cx={x} cy={y} r={1.8} fill="#0f172a" opacity={0.6} />;
      })}
    </svg>
  );
}

export function FirstDigitPlot({
  points,
  xLabel,
  yLabel,
}: {
  points: FirstDigitPoint[];
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const maxValue = Math.max(
    0.01,
    ...points.flatMap((point) => [point.observed, point.benford])
  );
  const groupWidth = points.length > 0 ? innerWidth / points.length : innerWidth;

  const linePath = points
    .map((point, index) => {
      const x = PAD_LEFT + index * groupWidth + groupWidth * 0.5;
      const y = HEIGHT - PAD_BOTTOM - (point.benford / maxValue) * innerHeight;
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {points.map((point, index) => {
        const barHeight = (point.observed / maxValue) * innerHeight;
        const x = PAD_LEFT + index * groupWidth + groupWidth * 0.2;
        return (
          <rect
            key={point.digit}
            x={x}
            y={HEIGHT - PAD_BOTTOM - barHeight}
            width={Math.max(4, groupWidth * 0.6)}
            height={barHeight}
            fill="#0f172a"
            opacity={0.75}
          />
        );
      })}
      {points.length > 1 ? (
        <path d={linePath} fill="none" stroke="#ef4444" strokeWidth={2} />
      ) : null}
    </svg>
  );
}

export function DuplicateFrequencyPlot({
  points,
  xLabel,
  yLabel,
}: {
  points: DuplicateFrequencyPoint[];
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const maxValue = Math.max(1, ...points.map((point) => point.percentage));
  const barWidth = points.length > 0 ? innerWidth / points.length : innerWidth;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {points.map((point, index) => {
        const height = (point.percentage / maxValue) * innerHeight;
        const x = PAD_LEFT + index * barWidth;
        const y = HEIGHT - PAD_BOTTOM - height;
        return (
          <rect
            key={`${point.occurrences}-${index}`}
            x={x}
            y={y}
            width={Math.max(1, barWidth - 1)}
            height={height}
            fill="#0ea5e9"
            opacity={0.85}
          />
        );
      })}
    </svg>
  );
}

export function CategoryBarPlot({
  points,
  color = "#0f172a",
  xLabel,
  yLabel,
}: {
  points: SampleMetricPoint[];
  color?: string;
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const maxValue = Math.max(1, ...points.map((point) => point.value));
  const barWidth = points.length > 0 ? innerWidth / points.length : innerWidth;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {points.map((point, index) => {
        const height = (point.value / maxValue) * innerHeight;
        const x = PAD_LEFT + index * barWidth;
        const y = HEIGHT - PAD_BOTTOM - height;
        return (
          <rect
            key={`${point.sample}-${index}`}
            x={x}
            y={y}
            width={Math.max(1, barWidth - 1)}
            height={height}
            fill={color}
            opacity={0.85}
          />
        );
      })}
    </svg>
  );
}

export function BoxPlotSummaryPlot({
  points,
  xLabel,
  yLabel,
}: {
  points: BoxplotPoint[];
  xLabel?: string;
  yLabel?: string;
}) {
  const { innerWidth, innerHeight } = chartBounds();
  const allValues = points.flatMap((point) => [
    point.min,
    point.q1,
    point.median,
    point.q3,
    point.max,
  ]);
  const minVal = allValues.length > 0 ? Math.min(...allValues) : 0;
  const maxVal = allValues.length > 0 ? Math.max(...allValues) : 1;
  const span = maxVal - minVal || 1;
  const groupWidth = points.length > 0 ? innerWidth / points.length : innerWidth;

  const mapY = (value: number) =>
    HEIGHT - PAD_BOTTOM - ((value - minVal) / span) * innerHeight;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-72 w-full">
      {axisLine()}
      {axisLabels(xLabel, yLabel)}
      {points.map((point, index) => {
        const xCenter = PAD_LEFT + index * groupWidth + groupWidth / 2;
        const boxWidth = Math.max(6, groupWidth * 0.45);
        const yMin = mapY(point.min);
        const yQ1 = mapY(point.q1);
        const yMedian = mapY(point.median);
        const yQ3 = mapY(point.q3);
        const yMax = mapY(point.max);

        return (
          <g key={`${point.sample}-${index}`}>
            <line x1={xCenter} y1={yMin} x2={xCenter} y2={yMax} stroke="#0f172a" strokeWidth={1} />
            <rect
              x={xCenter - boxWidth / 2}
              y={yQ3}
              width={boxWidth}
              height={Math.max(1, yQ1 - yQ3)}
              fill="#0ea5e9"
              opacity={0.35}
              stroke="#0369a1"
            />
            <line
              x1={xCenter - boxWidth / 2}
              y1={yMedian}
              x2={xCenter + boxWidth / 2}
              y2={yMedian}
              stroke="#0f172a"
              strokeWidth={2}
            />
          </g>
        );
      })}
    </svg>
  );
}
