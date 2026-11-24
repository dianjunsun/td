import { useEffect, useRef, useState } from "react";
import type { Bar } from "../types";

const WIDTH = 720;
const HEIGHT = 344;
const LEFT = 32;
const RIGHT = 64;
const BOTTOM = 22;
const UP = "#8e2e2e";
const DOWN = "#1c6b48";
const AVG = "#b5812f";
const GRID = "#e6dccb";

type View = { key: string; start: number; count: number; length: number };

export function StockChart({ bars, kind, prevClose, resetKey }: {
  bars: Bar[];
  kind: "line" | "candle";
  prevClose: number | null;
  resetKey: string;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const view = useRef<View>({ key: "", start: 0, count: 0, length: 0 });
  const drag = useRef<{ x: number; start: number; moved: boolean } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [, redraw] = useState(0);

  if (view.current.key !== resetKey) {
    const count = kind === "line" ? bars.length : Math.min(90, bars.length);
    view.current = { key: resetKey, start: Math.max(0, bars.length - count), count: Math.max(count, 1), length: bars.length };
  } else if (bars.length !== view.current.length) {
    const count = Math.min(view.current.count, bars.length);
    const pinned = view.current.start + view.current.count >= view.current.length;
    const start = pinned ? Math.max(0, bars.length - count) : Math.min(view.current.start, Math.max(0, bars.length - count));
    view.current = { key: resetKey, start, count, length: bars.length };
  }

  useEffect(() => {
    const node = svgRef.current;
    if (!node) return;
    function onWheel(event: WheelEvent) {
      event.preventDefault();
      const x = viewBoxX(node!, event.clientX);
      const ratio = x == null ? 0.5 : clamp((x - LEFT) / (WIDTH - RIGHT - LEFT), 0, 1);
      zoom(event.deltaY, ratio);
    }
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [bars.length, kind]);

  function zoom(delta: number, ratio: number) {
    const current = view.current;
    const next = clamp(Math.round(current.count * (delta > 0 ? 1.25 : 0.8)), kind === "line" ? 30 : 20, bars.length);
    const focus = current.start + ratio * current.count;
    const start = clamp(Math.round(focus - ratio * next), 0, Math.max(0, bars.length - next));
    view.current = { ...current, start, count: next };
    redraw((value) => value + 1);
  }

  const { start, count } = view.current;
  const visible = bars.slice(start, start + count);
  const hovered = hover == null ? null : visible[hover] || null;
  const hasVolume = visible.some((bar) => bar.volume != null);
  const priceBottom = hasVolume ? 196 : HEIGHT - BOTTOM - 8;
  const volumeTop = 210;
  const volumeBottom = HEIGHT - BOTTOM;
  const highs = visible.flatMap((bar) => [bar.high, bar.avg || bar.high]);
  const lows = visible.flatMap((bar) => [bar.low, bar.avg || bar.low]);
  if (kind === "line" && prevClose != null) {
    highs.push(prevClose);
    lows.push(prevClose);
  }
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const span = max - min || 1;
  const slot = (WIDTH - LEFT - RIGHT) / Math.max(visible.length, 1);
  const barX = (index: number) => LEFT + index * slot + slot / 2;
  const y = (value: number) => 8 + ((max - value) / span) * (priceBottom - 8);
  const maxVolume = Math.max(1, ...visible.map((bar) => bar.volume || 0));
  const ticks = timeTicks(visible);

  function indexAt(clientX: number) {
    const svg = svgRef.current;
    if (!svg) return null;
    const x = viewBoxX(svg, clientX);
    if (x == null || x < LEFT || x > WIDTH - RIGHT) return null;
    return clamp(Math.floor((x - LEFT) / slot), 0, visible.length - 1);
  }

  return (
    <div className={`chart ${dragging ? "dragging" : ""}`}>
      <svg
        ref={svgRef}
        className="chart-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={kind === "line" ? "分时" : "K线"}
        onPointerDown={(event) => {
          drag.current = { x: event.clientX, start, moved: false };
          setDragging(true);
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const active = drag.current;
          if (!active) {
            setHover(indexAt(event.clientX));
            return;
          }
          const from = svgRef.current ? viewBoxX(svgRef.current, active.x) : null;
          const to = svgRef.current ? viewBoxX(svgRef.current, event.clientX) : null;
          const shift = from == null || to == null ? 0 : Math.round((from - to) / slot);
          if (Math.abs(event.clientX - active.x) > 3) active.moved = true;
          view.current = { ...view.current, start: clamp(active.start + shift, 0, Math.max(0, bars.length - count)) };
          setHover(active.moved ? null : indexAt(event.clientX));
          redraw((value) => value + 1);
        }}
        onPointerUp={() => { drag.current = null; setDragging(false); }}
        onPointerLeave={() => { if (!drag.current) setHover(null); }}
      >
        {[0, 0.5, 1].map((mark) => {
          const price = max - span * mark;
          const line = y(price);
          const tone = prevClose == null ? "#8a8175" : price > prevClose ? UP : price < prevClose ? DOWN : "#8a8175";
          return (
            <g key={mark}>
              <line x1={LEFT} x2={WIDTH - RIGHT} y1={line} y2={line} stroke={GRID} strokeWidth="1" />
              <text x={WIDTH - 4} y={line + 4} textAnchor="end" fontSize="11" fill={tone}>{price.toFixed(2)}</text>
            </g>
          );
        })}
        {kind === "line" && prevClose != null ? <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(prevClose)} y2={y(prevClose)} stroke="#8a8175" strokeDasharray="4 4" /> : null}
        {hasVolume ? (
          <>
            <line x1={LEFT} x2={WIDTH - RIGHT} y1={volumeTop - 6} y2={volumeTop - 6} stroke={GRID} />
            <text x={WIDTH - 4} y={volumeTop + 12} textAnchor="end" fontSize="11" fill="#8a8175">{volumeText(maxVolume)}</text>
          </>
        ) : null}
        {ticks.map((tick) => {
          const x = barX(tick.index);
          return (
            <g key={`${tick.index}-${tick.label}`}>
              <line x1={x} x2={x} y1={priceBottom} y2={hasVolume ? volumeBottom : priceBottom + 5} stroke={GRID} />
              <text x={x} y={HEIGHT - 6} textAnchor="middle" fontSize="11" fill="#8a8175">{tick.label}</text>
            </g>
          );
        })}
        {visible.map((bar, index) => {
          const x = barX(index);
          const up = bar.close >= bar.open;
          const color = up ? UP : DOWN;
          if (hasVolume && bar.volume != null) {
            const height = Math.max(1, (bar.volume / maxVolume) * (volumeBottom - volumeTop));
            return <rect key={`v-${bar.trade_date}`} x={x - Math.max(1, slot * 0.28)} y={volumeBottom - height} width={Math.max(1.5, slot * 0.56)} height={height} fill={color} opacity="0.45" />;
          }
          return null;
        })}
        {kind === "candle" ? visible.map((bar, index) => {
          const x = barX(index);
          const up = bar.close >= bar.open;
          const color = up ? UP : DOWN;
          const top = y(Math.max(bar.open, bar.close));
          const body = Math.max(1, y(Math.min(bar.open, bar.close)) - top);
          const wick = Math.max(1.4, slot * 0.26);
          return (
            <g key={bar.trade_date}>
              <line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} stroke={color} strokeWidth="1" />
              <rect x={x - wick} y={top} width={wick * 2} height={body} fill={color} />
            </g>
          );
        }) : (
          <>
            <polyline fill="none" stroke={UP} strokeWidth="1.6" points={linePoints(visible, slot, (bar) => y(bar.close))} />
            {visible.some((bar) => bar.avg != null) ? <polyline fill="none" stroke={AVG} strokeWidth="1.2" points={linePoints(visible, slot, (bar) => bar.avg == null ? null : y(bar.avg))} /> : null}
          </>
        )}
        {hovered && hover != null ? (
          <line x1={barX(hover)} x2={barX(hover)} y1="8" y2={hasVolume ? volumeBottom : priceBottom} stroke="#5c564e" strokeDasharray="3 3" />
        ) : null}
      </svg>
      {hovered ? <div className="chart-tip">{tip(hovered, kind)}</div> : null}
    </div>
  );
}

function viewBoxX(svg: SVGSVGElement, clientX: number): number | null {
  const matrix = svg.getScreenCTM();
  if (!matrix) return null;
  const point = svg.createSVGPoint();
  point.x = clientX;
  point.y = 0;
  return point.matrixTransform(matrix.inverse()).x;
}

function timeTicks(bars: Bar[]) {
  if (bars.length < 2) return bars.map((bar, index) => ({ index, label: axisLabel(bar.trade_date) }));
  const days = new Set(bars.map((bar) => bar.trade_date.slice(0, 10)));
  const timed = bars[0].trade_date.includes(":");
  if (timed && days.size === 1) {
    return ["09:30", "10:30", "11:30", "14:00", "15:00"].flatMap((mark) => {
      const index = bars.findIndex((bar) => bar.trade_date.slice(11, 16) >= mark);
      return index < 0 ? [] : [{ index, label: mark }];
    }).filter((tick, index, all) => all.findIndex((item) => item.index === tick.index) === index);
  }
  if (timed && days.size <= 8) {
    const seen = new Set<string>();
    const ticks: { index: number; label: string }[] = [];
    bars.forEach((bar, index) => {
      const day = bar.trade_date.slice(5, 10);
      if (!seen.has(day)) {
        seen.add(day);
        ticks.push({ index, label: day });
      }
    });
    return ticks;
  }
  return [0, 0.25, 0.5, 0.75, 1].map((mark) => {
    const index = Math.round(mark * (bars.length - 1));
    return { index, label: axisLabel(bars[index].trade_date) };
  }).filter((tick, index, all) => all.findIndex((item) => item.index === tick.index) === index);
}

function axisLabel(stamp: string) {
  return stamp.includes(":") ? stamp.slice(5, 16) : stamp.slice(0, 10);
}

function linePoints(bars: Bar[], slot: number, point: (bar: Bar) => number | null) {
  return bars.map((bar, index) => {
    const y = point(bar);
    return y == null ? "" : `${LEFT + index * slot + slot / 2},${y}`;
  }).filter(Boolean).join(" ");
}

function tip(bar: Bar, kind: "line" | "candle") {
  const head = bar.trade_date;
  if (kind === "line") {
    return `${head}  价 ${bar.close}  均 ${bar.avg ?? "—"}  量 ${volumeText(bar.volume)}`;
  }
  return `${head}  开 ${bar.open}  高 ${bar.high}  低 ${bar.low}  收 ${bar.close}  量 ${volumeText(bar.volume)}`;
}

function volumeText(value: number | null | undefined) {
  if (value == null) return "—";
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(2)}万`;
  return String(Math.round(value));
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
