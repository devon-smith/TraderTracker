import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

// Local view type so rendering doesn't depend on the generated Prisma types.
type Row = {
  platform: string;
  walletId: string;
  tradeCount: number | null;
  totalVolume: number | null;
  totalPnl: number | null;
  winRate: number | null;
  topCategory: string | null;
  score: number | null;
};

function fmt(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export default async function LeaderboardPage() {
  let rows: Row[] = [];
  let error: string | null = null;
  try {
    rows = (await prisma.candidateScore.findMany({
      orderBy: { score: "desc" },
      take: 100,
    })) as Row[];
  } catch (err) {
    error = String(err);
  }

  return (
    <div>
      <h1>Candidate leaderboard</h1>
      <p style={{ color: "#9aa4b2" }}>
        Smart-money wallets ranked by computed score. Populated by the analytics
        scoring job into <code>candidate_score</code>.
      </p>

      {error ? (
        <p style={{ color: "#ff6b6b" }}>Database unreachable: {error}</p>
      ) : rows.length === 0 ? (
        <p style={{ color: "#6b7280" }}>
          No scored candidates yet. Run the ingestion + scoring jobs to populate
          this view.
        </p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "#9aa4b2", borderBottom: "1px solid #1c2230" }}>
              <th style={{ padding: 8 }}>#</th>
              <th style={{ padding: 8 }}>Wallet</th>
              <th style={{ padding: 8 }}>Platform</th>
              <th style={{ padding: 8, textAlign: "right" }}>Trades</th>
              <th style={{ padding: 8, textAlign: "right" }}>Volume</th>
              <th style={{ padding: 8, textAlign: "right" }}>PnL</th>
              <th style={{ padding: 8, textAlign: "right" }}>Win%</th>
              <th style={{ padding: 8 }}>Top cat</th>
              <th style={{ padding: 8, textAlign: "right" }}>Score</th>
            </tr>
          </thead>
          <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
            {rows.map((r: Row, i: number) => (
              <tr key={`${r.platform}:${r.walletId}`} style={{ borderBottom: "1px solid #141a26" }}>
                <td style={{ padding: 8, color: "#6b7280" }}>{i + 1}</td>
                <td style={{ padding: 8, fontFamily: "ui-monospace, monospace" }}>
                  {r.walletId.slice(0, 10)}…
                </td>
                <td style={{ padding: 8 }}>{r.platform}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{fmt(r.tradeCount)}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{fmt(r.totalVolume)}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{fmt(r.totalPnl)}</td>
                <td style={{ padding: 8, textAlign: "right" }}>
                  {r.winRate === null || r.winRate === undefined
                    ? "—"
                    : `${(r.winRate * 100).toFixed(0)}%`}
                </td>
                <td style={{ padding: 8 }}>{r.topCategory ?? "—"}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{fmt(r.score, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
