"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="page-stack">
      <section className="panel empty-state">
        <div><h2>Could not load recovery data</h2><p>Confirm FastAPI is running on the configured API URL.</p><button className="button primary" onClick={reset}>Try again</button></div>
      </section>
    </main>
  );
}
