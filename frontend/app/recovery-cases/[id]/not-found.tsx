import Link from "next/link";

export default function CaseNotFound() {
  return <main className="page-stack"><section className="panel empty-state"><div><h1>Recovery case not found</h1><p>The case may have been removed by a demo reset.</p><Link className="button primary" href="/recovery-cases">Return to cases</Link></div></section></main>;
}
