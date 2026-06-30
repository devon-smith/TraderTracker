import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

async function getHealth() {
  try {
    const [{ count: trades }] = await prisma.$queryRaw<{ count: bigint }[]>`
      SELECT count(*)::bigint AS count FROM trade`;
    const candidates = await prisma.candidateScore.count();
    const flows = await prisma.kalshiFlow.count();
    return { ok: true, trades: Number(trades), candidates, flows };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

export default async function HealthPage() {
  const h = await getHealth();
  return (
    <div>
      <h1>Health</h1>
      {h.ok ? (
        <table style={{ borderCollapse: "collapse" }}>
          <tbody>
            {[
              ["Database", "connected"],
              ["Trades", String(h.trades)],
              ["Candidate scores", String(h.candidates)],
              ["Kalshi flow rows", String(h.flows)],
            ].map(([k, v]) => (
              <tr key={k}>
                <td style={{ padding: "6px 24px 6px 0", color: "#9aa4b2" }}>{k}</td>
                <td style={{ padding: "6px 0", fontVariantNumeric: "tabular-nums" }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "#ff6b6b" }}>Database unreachable: {h.error}</p>
      )}
    </div>
  );
}
