import { useEffect, useRef } from "react";
import { createChart, ColorType, type IChartApi } from "lightweight-charts";
import { api } from "../api";

// TradingView Lightweight Charts candlestick + trade entry markers — the
// "modern terminal" look D3 asks for, and the thing Streamlit/Plotly can't match
// for live feel. Loads bars + trades from the API and overlays markers.
export function Chart({ symbol }: { symbol: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 460,
      layout: { background: { type: ColorType.Solid, color: "#131826" }, textColor: "#e6e9ef" },
      grid: { vertLines: { color: "#1f2740" }, horzLines: { color: "#1f2740" } },
      timeScale: { timeVisible: true },
    });
    chartRef.current = chart;
    const candle = chart.addCandlestickSeries({
      upColor: "#16c784", downColor: "#ea3943",
      wickUpColor: "#16c784", wickDownColor: "#ea3943", borderVisible: false,
    });

    let cancelled = false;
    const load = async () => {
      try {
        const [bars, trades] = await Promise.all([api.bars(symbol, "5m", 200), api.trades(200)]);
        if (cancelled) return;
        const toSec = (s: string) => Math.floor(new Date(s).getTime() / 1000) as any;
        candle.setData(bars.map((b) => ({
          time: toSec(b.ts), open: b.o, high: b.h, low: b.l, close: b.c,
        })));
        // entry markers for this symbol
        const markers = trades
          .filter((t) => t.symbol === symbol)
          .map((t) => ({
            time: toSec(t.entry_ts),
            position: t.side === "BUY" ? "belowBar" : "aboveBar",
            color: t.side === "BUY" ? "#16c784" : "#ea3943",
            shape: t.side === "BUY" ? "arrowUp" : "arrowDown",
            text: `${t.strategy} ${t.side}`,
          })) as any;
        candle.setMarkers(markers);
      } catch { /* backend not up */ }
    };
    load();
    const id = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(id); chart.remove(); };
  }, [symbol]);

  return <div ref={ref} style={{ border: "1px solid #1f2740", borderRadius: 10 }} />;
}
