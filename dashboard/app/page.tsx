import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1>Bellwether</h1>
      <p style={{ color: "#9aa4b2", maxWidth: 640 }}>
        Prediction-market trader intelligence. Read-only research surface over the
        canonical ingestion database. Determine whether top traders&apos; edges are{" "}
        <em>trackable</em> or <em>reverse-engineerable</em>.
      </p>
      <ul style={{ lineHeight: 1.9 }}>
        <li>
          <Link href="/leaderboard" style={{ color: "#9bb6ff" }}>
            Candidate leaderboard
          </Link>{" "}
          — ranked smart-money wallets (from <code>candidate_score</code>).
        </li>
        <li>
          <Link href="/health" style={{ color: "#9bb6ff" }}>
            Health
          </Link>{" "}
          — database connectivity and row counts.
        </li>
      </ul>
      <p style={{ color: "#6b7280", fontSize: 13 }}>
        Experiment A (trackability) and Experiment B (reverse-engineering) views
        land once their pipelines write results tables.
      </p>
    </div>
  );
}
